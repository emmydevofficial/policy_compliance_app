"""Bring an empty database to a state where the whole application can be demonstrated.

    python manage.py seed_demo [--reset] [--force-in-production]

All users get the password <DEMO_PASSWORD>. Refuses to run when DEBUG is False unless
--force-in-production is given.
"""

import json
import random
import shutil
from datetime import date, timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import NotificationPreference, Role, User
from apps.core.pdfgen import simple_pdf
from apps.notifications import services as notices
from apps.notifications.defaults import DEFAULT_TEMPLATES
from apps.notifications.holidays import nigerian_holidays
from apps.notifications.models import (
    Holiday,
    NotificationOutbox,
    NotificationTemplate,
    OutboxKind,
    OutboxStatus,
    ReminderRule,
)
from apps.obligations.models import Obligation, RegulatoryInstrument
from apps.obligations.reference import DEPARTMENTS, INSTRUMENTS
from apps.obligations.services import sync_obligations
from apps.organisation.models import Department
from apps.workflow import services as wf
from apps.workflow.files import REQUEST_TYPES, SUBMISSION_TYPES, validate_upload
from apps.workflow.models import ComplianceStatus, EvidenceRequest, ReportingPeriod, RequestStatus

DEMO_PASSWORD = "<DEMO_PASSWORD>"
FIRST = [
    "Adaeze",
    "Babatunde",
    "Chinedu",
    "Damilola",
    "Emeka",
    "Funmilayo",
    "Garba",
    "Hauwa",
    "Ifeanyi",
    "Jumoke",
    "Kelechi",
    "Lami",
    "Musa",
    "Ngozi",
    "Olumide",
    "Patience",
    "Rasheed",
    "Sadiya",
    "Tunde",
    "Uche",
    "Yetunde",
    "Zainab",
    "Ahmed",
    "Bisi",
]
LAST = [
    "Okafor",
    "Adeyemi",
    "Bello",
    "Eze",
    "Ibrahim",
    "Olawale",
    "Nwosu",
    "Abubakar",
    "Okonkwo",
    "Adebayo",
    "Danjuma",
    "Ogunleye",
    "Umar",
    "Chukwu",
    "Afolabi",
    "Yusuf",
    "Obi",
    "Lawal",
    "Nnamdi",
    "Oyelaran",
    "Ekwueme",
    "Salisu",
    "Balogun",
    "Ojo",
]


class Command(BaseCommand):
    help = (
        "Seed a demonstration dataset (instruments, departments, 82 obligations, users, requests)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", help="Wipe the database (and stored files) first."
        )
        parser.add_argument(
            "--force-in-production", action="store_true", help="Allow running when DEBUG is False."
        )

    def handle(self, *args, reset: bool, force_in_production: bool, **opts):
        if not settings.DEBUG and not force_in_production:
            raise CommandError(
                "DEBUG is False. seed_demo creates users with a known password; "
                "pass --force-in-production if you really mean it."
            )
        if reset:
            call_command("flush", interactive=False, verbosity=0)
            root = settings.PRIVATE_MEDIA_ROOT
            if root.exists():
                for child in root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            self.stdout.write("Database flushed.")
        elif User.objects.exists() or Obligation.objects.exists():
            raise CommandError("The database already has data. Use --reset to start again.")

        self.rng = random.Random(2026)
        self.today = timezone.localdate()
        with notices.deferred_sending(), transaction.atomic():
            self.instruments()
            depts = self.departments()
            self.obligations()
            self.users(depts)
            period = self.period()
            self.holidays()
            self.templates()
            ReminderRule.get()
            self.requests(period)
            self.request_pdfs(period)
            # Everything queued while seeding is history, not news: mark it sent.
            now = timezone.now()
            NotificationOutbox.objects.filter(status=OutboxStatus.PENDING).update(
                status=OutboxStatus.SENT, sent_at=now, attempts=1
            )
        self.summary()

    # --- reference data ------------------------------------------------------------------
    def instruments(self):
        for name, code, citation, desc in INSTRUMENTS:
            RegulatoryInstrument.objects.get_or_create(
                short_code=code, defaults={"name": name, "citation": citation, "description": desc}
            )

    def departments(self) -> list[Department]:
        out = []
        for name, code in DEPARTMENTS:
            d, _ = Department.objects.get_or_create(name=name, defaults={"code": code})
            out.append(d)
        return out

    def obligations(self):
        path = settings.BASE_DIR / "obligations.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        report = sync_obligations(rows)
        self.stdout.write(f"Obligations: {len(report.created)} created.")
        for note in report.notes:
            self.stdout.write(f"  {note}")

    def _name(self, i: int) -> str:
        return f"{FIRST[i % len(FIRST)]} {LAST[(i * 7 + 3) % len(LAST)]}"

    def _user(self, email, full_name, role, dept=None, gm=False, title="", **extra) -> User:
        if not hasattr(self, "_hash"):
            from django.contrib.auth.hashers import make_password

            self._hash = make_password(DEMO_PASSWORD)  # hashing once keeps the seed quick
        user = User.objects.create_user(
            email=email,
            password=None,
            full_name=full_name,
            role=role,
            department=dept,
            is_department_gm=gm,
            job_title=title,
            **extra,
        )
        user.password = self._hash
        user.save(update_fields=["password"])
        NotificationPreference.objects.get_or_create(user=user)
        return user

    def users(self, depts: list[Department]):
        self.admin = self._user(
            "gm.regcompliance@example.org",
            "Olufemi Adewale",
            Role.ADMIN,
            title="GM, Regulation & Compliance",
            is_staff=True,
            is_superuser=True,
        )
        self.officers: dict[int, User] = {}
        for i, d in enumerate(depts):
            code = d.code.lower()
            gm = self._user(
                f"gm.{code}@example.org",
                self._name(i * 2),
                Role.OFFICER,
                d,
                True,
                f"General Manager, {d.name}",
            )
            d.gm = gm
            d.save()
            self.officers[d.pk] = self._user(
                f"officer.{code}@example.org",
                self._name(i * 2 + 1),
                Role.OFFICER,
                d,
                False,
                f"Compliance Officer, {d.name}",
            )
        self._user(
            "exec.md@example.org", "Amina Suleiman", Role.EXECUTIVE, title="Managing Director / CEO"
        )
        self._user(
            "exec.ed@example.org",
            "Chukwuemeka Obi",
            Role.EXECUTIVE,
            title="Executive Director, Transmission Services",
        )

    def period(self) -> ReportingPeriod:
        q = (self.today.month - 1) // 3
        start = date(self.today.year, q * 3 + 1, 1)
        end_month = q * 3 + 3
        end = date(self.today.year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
        return ReportingPeriod.objects.create(
            name=f"Q{q + 1} {self.today.year}", start_date=start, end_date=end, is_open=True
        )

    def holidays(self):
        for year in (self.today.year, self.today.year + 1):
            for d, name in nigerian_holidays(year):
                Holiday.objects.get_or_create(date=d, defaults={"name": name})

    def templates(self):
        for key, (name, subject, body) in DEFAULT_TEMPLATES.items():
            NotificationTemplate.objects.get_or_create(
                key=key, defaults={"name": name, "subject_template": subject, "body_template": body}
            )

    # --- workflow ------------------------------------------------------------------------
    def _evidence(self, ob: Obligation, n: int = 1):
        files = []
        for i in range(n):
            pdf = simple_pdf(
                [
                    f"{ob.obligation_id} evidence {i + 1}",
                    ob.document_reference,
                    "Demonstration document generated by seed_demo.",
                ]
            )
            upload = SimpleUploadedFile(
                f"{ob.obligation_id}-evidence-{i + 1}.pdf", pdf, content_type="application/pdf"
            )
            files.append(validate_upload(upload, SUBMISSION_TYPES))
        return files

    def _submit(self, req: EvidenceRequest, status: str = ComplianceStatus.COMPLIANT):
        ob = req.obligation
        data = {
            "compliance_status": status,
            "evidence_available": "YES",
            "evidence_description": f"{ob.evidence_items[0] if ob.evidence_items else 'Evidence'}"
            f" for {req.period.name}, attached.",
            "date_of_last_review": self.today - timedelta(days=self.rng.randint(10, 80)),
            "next_review_due": self.today + timedelta(days=self.rng.randint(60, 200)),
        }
        if status in (ComplianceStatus.PARTIALLY_COMPLIANT, ComplianceStatus.NON_COMPLIANT):
            data.update(
                action_required="Close the documentation gap and file the outstanding return.",
                action_owner=req.assigned_department.gm.full_name,
                target_resolution_date=self.today + timedelta(days=self.rng.randint(10, 28)),
            )
        if status == ComplianceStatus.UNDER_REVIEW:
            data["remarks"] = "Internal review of the evidence is still in progress."
        submitter = self.officers[req.assigned_department_id]
        return wf.submit(req, submitter, data, self._evidence(ob, self.rng.randint(1, 2)))

    def requests(self, period: ReportingPeriod):
        obligations = list(Obligation.objects.active().select_related("primary_department"))
        self.rng.shuffle(obligations)
        n = len(obligations)
        plan = (
            ["verified"] * round(n * 0.24)
            + ["submitted"] * round(n * 0.16)
            + ["awaiting"] * round(n * 0.25)
            + ["overdue"] * round(n * 0.15)
            + ["returned"] * round(n * 0.10)
        )
        rest = n - len(plan)
        plan += ["closed_na"] * (rest // 2) + ["under_review"] * (rest - rest // 2)
        overdue_reqs = []
        for ob, kind in zip(obligations, plan, strict=False):
            if kind == "overdue":
                due = self.today - timedelta(days=self.rng.randint(1, 21))
            elif kind in ("awaiting", "returned"):
                due = self.today + timedelta(days=self.rng.randint(1, 42))
            else:
                due = self.today + timedelta(days=self.rng.randint(-21, 42))
            officer = self.officers[ob.primary_department_id]
            result = wf.create_requests(
                obligations=[ob],
                period=period,
                actor=self.admin,
                due_date=due,
                officer=officer,
                message="Please provide the evidence listed for this quarter.",
                issue_now=kind != "draft",
            )
            req = result.created[0]
            if kind == "verified":
                status = self.rng.choice(
                    [ComplianceStatus.COMPLIANT] * 4 + [ComplianceStatus.PARTIALLY_COMPLIANT]
                )
                wf.verify(self._submit(req, status), self.admin, "Evidence checked.")
            elif kind == "submitted":
                self._submit(
                    req,
                    self.rng.choice(
                        [ComplianceStatus.COMPLIANT] * 3 + [ComplianceStatus.NON_COMPLIANT]
                    ),
                )
            elif kind == "under_review":
                self._submit(req, ComplianceStatus.UNDER_REVIEW)
            elif kind == "returned":
                wf.return_submission(
                    self._submit(req),
                    self.admin,
                    "The attached return is for the previous quarter. "
                    "Please attach the current one.",
                )
            elif kind == "closed_na":
                wf.close_not_applicable(
                    req, "No activity under this obligation in the period.", self.admin
                )
            elif kind == "overdue":
                overdue_reqs.append(req)
        self._overdue_history(overdue_reqs)

    def _overdue_history(self, reqs: list[EvidenceRequest]):
        """Mark past-due requests overdue and write the reminders they would have had."""
        rule = ReminderRule.get()
        holidays = notices.holiday_set()
        report = notices.DailyReport(as_of=self.today, dry_run=False)
        notices.mark_overdue(self.today, report)
        for req in reqs:
            req.refresh_from_db()
            day = req.due_date - timedelta(days=15)
            while day < self.today:
                req.status = (
                    RequestStatus.AWAITING if day <= req.due_date else RequestStatus.OVERDUE
                )
                kind = notices.deadline_notice_due(req, day, rule, holidays)
                if kind:
                    self._history_row(req, kind, day, rule)
                if (
                    req.status == RequestStatus.OVERDUE
                    and req.escalated_to_gm_at is None
                    and notices.gm_escalation_due(req, day, holidays)
                ):
                    self._history_row(req, OutboxKind.ESCALATION_GM, day, rule)
                    req.escalated_to_gm_at = notices.lagos_datetime(day, rule.send_time)
                day += timedelta(days=1)
            req.status = RequestStatus.OVERDUE
            req.save(update_fields=["escalated_to_gm_at", "reminders_sent"])

    def _history_row(self, req, kind, day, rule):
        to = notices.addressees(req, kind, on=day)
        ctx = notices.request_context(req, today=day, officer=to.to)
        at = notices.lagos_datetime(day, rule.send_time)
        row = notices.build_row(kind, req, to, ctx, day, at)
        if row is None:
            return
        row.status = OutboxStatus.SENT
        row.sent_at = at
        row.attempts = 1
        row.save()
        if kind in notices.DEADLINE_KINDS:
            req.reminders_sent += 1

    def request_pdfs(self, period: ReportingPeriod):
        """A generated circular attached to two open requests (SPEC 11.9)."""
        from weasyprint import HTML

        reqs = list(
            EvidenceRequest.objects.filter(
                period=period, status=RequestStatus.AWAITING
            ).select_related("obligation")[:2]
        )
        for req in reqs:
            html = (
                "<html><body style='font-family:sans-serif;margin:40px'>"
                "<h1 style='color:#00849E'>Regulation &amp; Compliance circular</h1>"
                f"<p><strong>{req.obligation.obligation_id}</strong> – "
                f"{req.obligation.document_reference}</p>"
                f"<p>{req.obligation.description}</p>"
                "<h2>Evidence required</h2><ul>"
                + "".join(f"<li>{e}</li>" for e in req.obligation.evidence_items)
                + f"</ul><p>Deadline: <strong>{req.due_date:%d %B %Y}</strong></p>"
                "<p>Use the attached return format. Sample document generated by seed_demo.</p>"
                "</body></html>"
            )
            pdf = HTML(string=html).write_pdf()
            upload = SimpleUploadedFile(
                f"Circular-{req.obligation.obligation_id}.pdf", pdf, content_type="application/pdf"
            )
            wf.add_request_attachment(
                req,
                None,
                self.admin,
                clean=validate_upload(upload, REQUEST_TYPES),
                description="Circular and return format",
            )

    def summary(self):
        from django.db.models import Count

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        counts = dict(EvidenceRequest.objects.values_list("status").annotate(c=Count("pk")))
        self.stdout.write(
            "Requests by status: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )
        self.stdout.write(f"Outbox rows: {NotificationOutbox.objects.count()}")
        self.stdout.write(f"Users: {User.objects.count()} (password {DEMO_PASSWORD})")
        self.stdout.write("  Admin:     gm.regcompliance@example.org")
        self.stdout.write("  GM:        gm.hse@example.org (and gm.<code>@example.org)")
        self.stdout.write("  Officer:   officer.hse@example.org (and officer.<code>@example.org)")
        self.stdout.write("  Executive: exec.md@example.org, exec.ed@example.org")
