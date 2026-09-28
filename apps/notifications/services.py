"""Notices: who gets them, what they say, when they are due, and sending them.

Every notice becomes a NotificationOutbox row before anything is sent. The daily command
(`run_daily_notices`) calls `run_daily`; workflow services call `queue_event_notice`.
"""

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import NotificationPreference, Role, User
from apps.auditlog.services import Action, record
from apps.workflow.models import EvidenceRequest, RequestStatus, VerificationOutcome

from .models import (
    MAX_SEND_ATTEMPTS,
    Holiday,
    NotificationOutbox,
    NotificationTemplate,
    OutboxKind,
    OutboxStatus,
    ReminderRule,
)
from .rendering import render_notice
from .workdays import add_working_days, is_working_day, previous_working_day

logger = logging.getLogger("obligation_desk")

K = OutboxKind
S = RequestStatus

TEMPLATE_FOR_KIND = {
    K.REQUEST: "evidence_request",
    K.REMINDER: "reminder_before",
    K.FINAL: "final_notice",
    K.OVERDUE: "overdue_notice",
    K.ESCALATION_GM: "escalation_gm",
    K.ESCALATION_MGMT: "escalation_management",
    K.RECEIVED: "submission_received",
    K.RETURNED: "submission_returned",
    K.VERIFIED: "submission_verified",
    K.DIGEST: "weekly_digest",
}
DEADLINE_KINDS = (K.REMINDER, K.FINAL, K.OVERDUE)
REMINDER_STATUSES = (S.AWAITING, S.OVERDUE, S.RETURNED)


# --- time helpers -----------------------------------------------------------------------
def lagos_datetime(day: date, at) -> datetime:
    return timezone.make_aware(datetime.combine(day, at), timezone.get_default_timezone())


def holiday_set() -> set[date]:
    return set(Holiday.objects.values_list("date", flat=True))


# --- context ----------------------------------------------------------------------------
def absolute(path: str) -> str:
    return settings.SITE_URL.rstrip("/") + path


def request_context(
    req: EvidenceRequest,
    *,
    today: date | None = None,
    reason: str = "",
    officer: User | None = None,
    link: str | None = None,
) -> dict:
    """The fixed placeholder set from SPEC 9, as plain strings and numbers."""
    today = today or timezone.localdate()
    ob = req.obligation
    dept = req.assigned_department
    gms = list(dept.gm_users())
    officer = officer or req.assigned_officer
    days = (req.due_date - today).days
    return {
        "officer_name": officer.full_name if officer else f"{dept.name} team",
        "department_name": dept.name,
        "obligation_id": ob.obligation_id,
        "obligation_text": ob.description,
        "instrument": ob.instrument.name,
        "document_reference": ob.document_reference,
        "risk_level": ob.get_risk_level_display(),
        "evidence_list": "\n".join(
            f"- {e.strip()}" for e in req.evidence_required.split(";") if e.strip()
        ),
        "deadline": req.due_date.strftime("%A %d %B %Y"),
        "days_remaining": max(days, 0),
        "days_overdue": max(-days, 0),
        "consequence": ob.consequence,
        "upload_link": link or absolute(reverse("my:submit", args=[req.pk])),
        "gm_name": gms[0].full_name if gms else "the department GM",
        "period_name": req.period.name,
        "reason": reason,
    }


# --- recipients -------------------------------------------------------------------------
def _prefs(user: User) -> NotificationPreference:
    prefs = getattr(user, "notification_prefs", None)
    if prefs is None:
        prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    return prefs


def _with_delegates(users: list[User], on: date) -> list[User]:
    out: list[User] = []
    for u in users:
        if u not in out:
            out.append(u)
        d = u.active_delegate(on)
        if d is not None and d not in out:
            out.append(d)
    return out


@dataclass
class Addressees:
    to: User | None
    cc: list[User] = field(default_factory=list)

    @property
    def cc_emails(self) -> list[str]:
        return [u.email for u in self.cc if not self.to or u.email != self.to.email]


def addressees(
    req: EvidenceRequest, kind: str, *, on: date | None = None, submitter: User | None = None
) -> Addressees:
    """Who a notice about this request goes to, honouring preferences and delegation.
    Deadline reminders for High risk obligations ignore the opt-out (SPEC 3)."""
    on = on or timezone.localdate()
    dept = req.assigned_department
    high = req.obligation.risk_level == "HIGH"
    gms = list(dept.gm_users())

    if kind == K.ESCALATION_GM:
        primary, others = gms, []
    elif kind == K.ESCALATION_MGMT:
        primary, others = list(User.objects.active().filter(role=Role.EXECUTIVE)), []
    elif kind == K.RECEIVED:
        primary, others = [submitter or req.assigned_officer], []
    else:
        officers = list(
            User.objects.active()
            .filter(role=Role.OFFICER, department=dept, is_department_gm=False)
            .order_by("full_name")
        )
        if req.assigned_officer and req.assigned_officer.is_active:
            primary = [req.assigned_officer]
        else:
            primary = officers
        others = gms  # the department GM is copied on notices for the department

    people = [u for u in _with_delegates([u for u in primary if u], on) if u.is_active]
    people += [u for u in _with_delegates(others, on) if u.is_active and u not in people]
    if kind not in (K.ESCALATION_GM, K.ESCALATION_MGMT):
        people = [u for u in people if _prefs(u).wants(kind, high_risk=high)]
    if not people:
        return Addressees(to=None)
    return Addressees(to=people[0], cc=people[1:])


_local = threading.local()


@contextmanager
def deferred_sending():
    """Queue event notices without sending them straight away (used by seed_demo)."""
    _local.defer = True
    try:
        yield
    finally:
        _local.defer = False


# --- queueing ---------------------------------------------------------------------------
def _template(key: str) -> NotificationTemplate | None:
    return NotificationTemplate.objects.filter(key=key, is_active=True).first()


def build_row(
    kind: str,
    req: EvidenceRequest | None,
    to: Addressees,
    context: dict,
    scheduled_day: date,
    scheduled_for: datetime,
) -> NotificationOutbox | None:
    template = _template(TEMPLATE_FOR_KIND[kind])
    if template is None or to.to is None:
        return None
    subject, body, html = render_notice(template, context)
    return NotificationOutbox(
        request=req,
        recipient=to.to,
        recipient_email=to.to.email,
        cc_emails=to.cc_emails,
        template_key=template.key,
        kind=kind,
        subject=subject,
        body=body,
        body_html=html,
        scheduled_for=scheduled_for,
        scheduled_date=scheduled_day,
    )


def queue_event_notice(
    kind: str,
    req: EvidenceRequest,
    *,
    reason: str = "",
    submitter: User | None = None,
    send_now: bool = True,
):
    """A notice caused by something a person did: issue, receipt, return, verification.
    Queued now and sent straight after the transaction commits; if sending fails, the daily
    command retries it."""
    today = timezone.localdate()
    to = addressees(req, kind, on=today, submitter=submitter)
    officer = submitter if kind == K.RECEIVED else None
    ctx = request_context(req, today=today, reason=reason, officer=officer or to.to)
    row = build_row(kind, req, to, ctx, today, timezone.now())
    if row is None:
        return None
    row.save()
    if send_now and not getattr(_local, "defer", False):
        transaction.on_commit(lambda: send_row(row.pk))
    return row


def cancel_pending(req: EvidenceRequest) -> int:
    return NotificationOutbox.objects.filter(request=req, status=OutboxStatus.PENDING).update(
        status=OutboxStatus.CANCELLED, last_error="Cancelled by a workflow change"
    )


# --- the reminder schedule --------------------------------------------------------------
def returned_on(req: EvidenceRequest) -> date | None:
    sub = (
        req.submissions.filter(verification_outcome=VerificationOutcome.RETURNED)
        .order_by("-verified_at")
        .first()
    )
    return timezone.localdate(sub.verified_at) if sub and sub.verified_at else None


def deadline_notice_due(
    req: EvidenceRequest, day: date, rule: ReminderRule, holidays: set[date]
) -> str | None:
    """Which deadline notice, if any, this request should receive on `day`.

    - REMINDER on each of `days_before` calendar days before the deadline;
    - FINAL on the deadline itself;
    - OVERDUE every `repeat_every_working_days` working days after the deadline (or after
      the date it was returned, if later), up to `stop_after_count` times.
    With `working_days_only`, nothing is sent on a weekend or holiday; a before-deadline
    notice that would fall on one is brought forward to the previous working day.
    """
    if req.status not in REMINDER_STATUSES:
        return None
    wd = rule.working_days_only
    if wd and not is_working_day(day, holidays):
        return None

    def adjust(d: date) -> date:
        return previous_working_day(d, holidays) if wd else d

    due = req.due_date
    if rule.send_on_due_date and day <= due and adjust(due) == day:
        return K.FINAL
    if day < due:
        for n in rule.days_before:
            if adjust(due - timedelta(days=n)) == day:
                return K.REMINDER
        return None
    if day > due:
        anchor = due
        back = returned_on(req) if req.pk else None
        if back and back > anchor:
            anchor = back
        step = max(1, rule.repeat_every_working_days)
        k = 1
        while rule.stop_after_count is None or k <= rule.stop_after_count:
            d = (
                add_working_days(anchor, k * step, holidays)
                if wd
                else anchor + timedelta(days=k * step)
            )
            if d == day:
                return K.OVERDUE
            if d > day:
                break
            k += 1
    return None


def gm_escalation_due(req: EvidenceRequest, day: date, holidays: set[date]) -> bool:
    return (
        req.status == S.OVERDUE
        and req.escalated_to_gm_at is None
        and day >= add_working_days(req.due_date, req.escalate_gm_after_days, holidays)
    )


def mgmt_escalation_due(
    req: EvidenceRequest, day: date, rule: ReminderRule, holidays: set[date]
) -> bool:
    if rule.escalate_management_high_risk_only and req.obligation.risk_level != "HIGH":
        return False
    return (
        req.status == S.OVERDUE
        and req.escalated_to_management_at is None
        and day >= add_working_days(req.due_date, rule.escalate_management_after_days, holidays)
    )


# --- sending ----------------------------------------------------------------------------
def _guard_real_email() -> None:
    backend = settings.EMAIL_BACKEND
    if backend.endswith("smtp.EmailBackend") and not settings.ALLOW_REAL_EMAIL:
        raise ImproperlyConfigured(
            "Refusing to send real email: ALLOW_REAL_EMAIL is False in this environment."
        )


def send_row(pk: int) -> bool:
    row = NotificationOutbox.objects.filter(pk=pk, status=OutboxStatus.PENDING).first()
    if row is None:
        return False
    return _deliver(row)


def _deliver(row: NotificationOutbox) -> bool:
    try:
        _guard_real_email()
        msg = EmailMultiAlternatives(
            subject=row.subject,
            body=row.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[row.recipient_email],
            cc=row.cc_emails or None,
        )
        if row.body_html:
            msg.attach_alternative(row.body_html, "text/html")
        msg.send(fail_silently=False)
    except ImproperlyConfigured:
        raise
    except Exception as exc:  # delivery failure: record it and move on
        row.attempts += 1
        row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if row.attempts >= MAX_SEND_ATTEMPTS:
            row.status = OutboxStatus.FAILED
        row.save(update_fields=["attempts", "last_error", "status"])
        logger.warning("Notice %s failed (attempt %s): %s", row.pk, row.attempts, exc)
        return False
    row.attempts += 1
    row.status = OutboxStatus.SENT
    row.sent_at = timezone.now()
    row.save(update_fields=["attempts", "status", "sent_at"])
    if row.request_id and row.kind in DEADLINE_KINDS:
        EvidenceRequest.objects.filter(pk=row.request_id).update(
            reminders_sent=F("reminders_sent") + 1
        )
    return True


# --- the daily run ----------------------------------------------------------------------
@dataclass
class DailyReport:
    as_of: date
    dry_run: bool
    marked_overdue: list[str] = field(default_factory=list)
    created: list[NotificationOutbox] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    sent: list[NotificationOutbox] = field(default_factory=list)
    failed: list[NotificationOutbox] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        mode = "DRY RUN — nothing written, nothing sent" if self.dry_run else "LIVE"
        out = [f"Daily notices for {self.as_of:%A %d %B %Y} ({mode})", ""]
        out.append(f"1. Marked overdue: {len(self.marked_overdue)}")
        out += [f"   {x}" for x in self.marked_overdue]
        out.append(f"2-3,5. Notices created: {len(self.created)}")
        for r in self.created:
            ref = r.request.obligation.obligation_id if r.request_id else "—"
            cc = f" cc {', '.join(r.cc_emails)}" if r.cc_emails else ""
            out.append(
                f"   {r.kind:<15} {ref:<10} to {r.recipient_email}{cc} at "
                f"{timezone.localtime(r.scheduled_for):%Y-%m-%d %H:%M}"
            )
        out.append(f"   Escalations stamped: {len(self.escalations)}")
        out += [f"   {x}" for x in self.escalations]
        verb = "Would send" if self.dry_run else "Sent"
        out.append(f"4. {verb}: {len(self.sent)}")
        for r in self.sent:
            out.append(f"   {r.kind:<15} to {r.recipient_email}: {r.subject}")
        if self.failed:
            out.append(f"   Failed this run: {len(self.failed)}")
            out += [f"   {r.kind} to {r.recipient_email}: {r.last_error}" for r in self.failed]
        if self.skipped:
            out.append("Notes:")
            out += [f"   {x}" for x in self.skipped]
        return out


def _insert(row: NotificationOutbox | None, report: DailyReport) -> bool:
    """Insert a scheduled notice unless the same (request, kind, day) already exists."""
    if row is None:
        return False
    exists = NotificationOutbox.objects.filter(
        request=row.request, kind=row.kind, scheduled_date=row.scheduled_date
    )
    if row.request_id is None:
        exists = NotificationOutbox.objects.filter(
            request__isnull=True,
            recipient_email=row.recipient_email,
            kind=row.kind,
            scheduled_date=row.scheduled_date,
        )
    if exists.exists():
        return False
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        return False
    report.created.append(row)
    return True


def mark_overdue(as_of: date, report: DailyReport) -> None:
    stale = EvidenceRequest.objects.with_related().filter(
        status__in=(S.AWAITING, S.RETURNED), due_date__lt=as_of, period__is_open=True
    )
    for req in stale:
        req.transition_to(S.OVERDUE)
        req.save(update_fields=["status", "updated_at"])
        record(
            Action.REQUEST_OVERDUE,
            obj=req,
            detail=f"Deadline {req.due_date:%d %b %Y} passed; marked overdue by the daily run.",
        )
        report.marked_overdue.append(f"{req.obligation.obligation_id} (due {req.due_date})")
    lingering = EvidenceRequest.objects.filter(status=S.OVERDUE, due_date__gte=as_of)
    for req in lingering.select_related("obligation"):
        report.skipped.append(
            f"{req.obligation.obligation_id} is OVERDUE but its deadline ({req.due_date}) has "
            "been moved to the future. The transition table has no OVERDUE → AWAITING path, "
            "so it stays OVERDUE until submitted."
        )


def schedule_notices(
    as_of: date, rule: ReminderRule, holidays: set[date], report: DailyReport
) -> None:
    send_at = lagos_datetime(as_of, rule.send_time)
    open_reqs = (
        EvidenceRequest.objects.with_related()
        .filter(status__in=REMINDER_STATUSES, period__is_open=True)
        .prefetch_related("submissions")
    )
    for req in open_reqs:
        kind = deadline_notice_due(req, as_of, rule, holidays)
        if kind:
            to = addressees(req, kind, on=as_of)
            if to.to is None:
                report.skipped.append(f"{req.obligation.obligation_id}: no one to send {kind} to")
            else:
                ctx = request_context(req, today=as_of, officer=to.to)
                _insert(build_row(kind, req, to, ctx, as_of, send_at), report)

        # 3. escalations
        if gm_escalation_due(req, as_of, holidays):
            to = addressees(req, K.ESCALATION_GM, on=as_of)
            ctx = request_context(
                req,
                today=as_of,
                link=absolute(reverse("obligations:detail", args=[req.obligation.obligation_id])),
            )
            if to.to is not None:
                _insert(build_row(K.ESCALATION_GM, req, to, ctx, as_of, send_at), report)
            req.escalated_to_gm_at = send_at
            req.save(update_fields=["escalated_to_gm_at", "updated_at"])
            record(
                Action.NOTICE_ESCALATED,
                obj=req,
                detail=f"Escalated to department GM ({req.days_overdue} days overdue).",
            )
            report.escalations.append(f"{req.obligation.obligation_id} → department GM")
        if mgmt_escalation_due(req, as_of, rule, holidays):
            to = addressees(req, K.ESCALATION_MGMT, on=as_of)
            if to.to is None:
                report.skipped.append(
                    f"{req.obligation.obligation_id}: management escalation due, but there are "
                    "no active Executive users"
                )
                continue
            ctx = request_context(
                req,
                today=as_of,
                officer=None,
                link=absolute(reverse("obligations:detail", args=[req.obligation.obligation_id])),
            )
            _insert(build_row(K.ESCALATION_MGMT, req, to, ctx, as_of, send_at), report)
            req.escalated_to_management_at = send_at
            req.save(update_fields=["escalated_to_management_at", "updated_at"])
            record(Action.NOTICE_ESCALATED, obj=req, detail="Escalated to Executive Management.")
            report.escalations.append(f"{req.obligation.obligation_id} → Executive Management")


def _digest_context(title: str, lines: list[str], as_of: date) -> dict:
    return {
        "officer_name": "",
        "department_name": title,
        "period_name": getattr(_open_period(), "name", ""),
        "deadline": as_of.strftime("%A %d %B %Y"),
        "digest_lines": "\n".join(lines) if lines else "Nothing outstanding.",
        "upload_link": absolute("/"),
    }


def _open_period():
    from apps.workflow.models import ReportingPeriod

    return ReportingPeriod.current()


def build_digests(as_of: date, rule: ReminderRule, report: DailyReport) -> None:
    template = _template("weekly_digest")
    if template is None:
        return
    send_at = lagos_datetime(as_of, rule.send_time)
    open_reqs = list(
        EvidenceRequest.objects.with_related()
        .filter(status__in=(S.AWAITING, S.OVERDUE, S.RETURNED, S.SUBMITTED), period__is_open=True)
        .order_by("due_date")
    )

    def row_for(user: User, ctx: dict) -> NotificationOutbox:
        subject, body, html = render_notice(template, {**ctx, "officer_name": user.full_name})
        return NotificationOutbox(
            request=None,
            recipient=user,
            recipient_email=user.email,
            cc_emails=[],
            template_key=template.key,
            kind=K.DIGEST,
            subject=subject,
            body=body,
            body_html=html,
            scheduled_for=send_at,
            scheduled_date=as_of,
        )

    if as_of.weekday() == 4:  # Friday: department digest
        by_dept: dict[int, list[EvidenceRequest]] = {}
        for r in open_reqs:
            by_dept.setdefault(r.assigned_department_id, []).append(r)
        for reqs in by_dept.values():
            dept = reqs[0].assigned_department
            lines = [
                f"- {r.obligation.obligation_id}: {r.get_status_display()}, due "
                f"{r.due_date:%d %b %Y}"
                for r in reqs
            ]
            ctx = _digest_context(dept.name, lines, as_of)
            people = User.objects.active().filter(department=dept, role=Role.OFFICER)
            for user in people:
                if _prefs(user).weekly_digest:
                    _insert(row_for(user, ctx), report)

    if as_of.weekday() == 0:  # Monday: overdue digest to the ADMIN
        overdue = [r for r in open_reqs if r.status == S.OVERDUE]
        lines = [
            f"- {r.obligation.obligation_id} ({r.assigned_department.name}): "
            f"{(as_of - r.due_date).days} days overdue"
            for r in overdue
        ]
        failed = list(
            NotificationOutbox.objects.filter(
                status=OutboxStatus.FAILED, reported_in_digest=False
            ).exclude(kind=K.DIGEST)
        )
        if failed:
            lines += ["", "Notices that failed after five attempts:"]
            lines += [f"- {f.kind} to {f.recipient_email}: {f.last_error[:120]}" for f in failed]
        ctx = _digest_context("All departments (overdue)", lines, as_of)
        created_any = False
        for admin in User.objects.active().filter(role=Role.ADMIN):
            created_any = _insert(row_for(admin, ctx), report) or created_any
        if created_any and failed:
            NotificationOutbox.objects.filter(pk__in=[f.pk for f in failed]).update(
                reported_in_digest=True
            )


def send_due(as_of: date, rule: ReminderRule, report: DailyReport) -> None:
    cutoff = lagos_datetime(as_of, rule.send_time)
    if as_of == timezone.localdate():
        cutoff = max(cutoff, timezone.now())
    due = NotificationOutbox.objects.filter(
        status=OutboxStatus.PENDING, scheduled_for__lte=cutoff
    ).order_by("scheduled_for", "pk")
    if not rule.email_enabled:
        report.skipped.append(
            f"Email is switched off in the reminder rule; {due.count()} notices left pending."
        )
        return
    for row in due:
        if report.dry_run:
            report.sent.append(row)
            continue
        if _deliver(row):
            report.sent.append(row)
        else:
            report.failed.append(row)


class _DryRunRollback(Exception):
    pass


def run_daily(as_of: date | None = None, *, dry_run: bool = False) -> DailyReport:
    """SPEC 8, in order. With dry_run everything happens inside a transaction that is rolled
    back, and nothing is sent, so the report is exactly what a live run would do."""
    as_of = as_of or timezone.localdate()
    report = DailyReport(as_of=as_of, dry_run=dry_run)
    try:
        with transaction.atomic():
            rule = ReminderRule.get()
            holidays = holiday_set()
            mark_overdue(as_of, report)
            schedule_notices(as_of, rule, holidays, report)
            build_digests(as_of, rule, report)
            if dry_run:
                send_due(as_of, rule, report)
                raise _DryRunRollback  # undo every write
    except _DryRunRollback:
        return report
    send_due(as_of, rule, report)
    return report


def schedule_preview(
    req: EvidenceRequest, rule: ReminderRule | None = None, horizon_days: int = 60
) -> list[tuple[date, str]]:
    """The deadline notices a request would receive, for the create form and request page.
    Assumes the request stays unanswered."""
    rule = rule or ReminderRule.get()
    holidays = holiday_set()
    start = timezone.localdate()
    out = []
    probe = EvidenceRequest(
        obligation=req.obligation,
        due_date=req.due_date,
        status=S.AWAITING,
        escalate_gm_after_days=req.escalate_gm_after_days,
    )
    probe.pk = None
    for i in range(0, horizon_days + (req.due_date - start).days + 1):
        day = start + timedelta(days=i)
        if day > req.due_date:
            probe.status = S.OVERDUE
        kind = deadline_notice_due(probe, day, rule, holidays)
        if kind:
            out.append((day, OutboxKind(kind).label))
        if len(out) >= 14:
            break
    gm_day = add_working_days(req.due_date, req.escalate_gm_after_days, holidays)
    out.append((gm_day, "Escalation to department GM"))
    if not rule.escalate_management_high_risk_only or req.obligation.risk_level == "HIGH":
        out.append(
            (
                add_working_days(req.due_date, rule.escalate_management_after_days, holidays),
                "Escalation to Executive Management",
            )
        )
    return sorted(out)
