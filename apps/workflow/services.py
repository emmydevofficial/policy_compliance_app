"""Workflow actions. Each one validates, changes state through `transition_to`, writes its
audit events and queues its notices. Views call these and nothing else changes state."""

from dataclasses import dataclass, field
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.auditlog.services import Action, record
from apps.notifications import services as notices
from apps.notifications.models import OutboxKind
from apps.obligations.models import Obligation
from apps.organisation.models import Department

from .files import REQUEST_TYPES, CleanFile, validate_upload
from .models import (
    EvidenceAvailable,
    EvidenceRequest,
    ReportingPeriod,
    RequestAttachment,
    RequestStatus,
    Submission,
    SubmissionAttachment,
    VerificationOutcome,
)

S = RequestStatus


def _require_admin(actor: User) -> None:
    if actor is None or actor.role != Role.ADMIN:
        raise PermissionDenied


def _require_reason(reason: str, what: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(f"{what} requires a reason.")
    return reason


# --- request attachments ----------------------------------------------------------------
def add_request_attachment(
    req: EvidenceRequest,
    upload,
    actor: User,
    *,
    description: str = "",
    http_request=None,
    clean: CleanFile | None = None,
) -> RequestAttachment:
    _require_admin(actor)
    req.assert_editable()
    clean = clean or validate_upload(upload, REQUEST_TYPES)
    att = RequestAttachment(
        request=req,
        original_filename=clean.original_filename,
        content_type=clean.content_type,
        size_bytes=clean.size_bytes,
        sha256=clean.sha256,
        description=description[:255],
        uploaded_by=actor,
    )
    att.file.save(clean.content.name, clean.content, save=False)
    att.save()
    record(
        Action.FILE_UPLOADED,
        actor=actor,
        obj=att,
        request=http_request,
        detail=f"Request attachment {att.original_filename} ({att.size_bytes} bytes, "
        f"sha256 {att.sha256}) added to {req}.",
    )
    return att


# --- creating and issuing ---------------------------------------------------------------
@dataclass
class CreateResult:
    created: list[EvidenceRequest] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@transaction.atomic
def create_requests(
    *,
    obligations: list[Obligation],
    period: ReportingPeriod,
    actor: User,
    due_date: date,
    department: Department | None = None,
    officer: User | None = None,
    evidence_required: str = "",
    message: str = "",
    escalate_gm_after_days: int = 5,
    files: list[CleanFile] | None = None,
    issue_now: bool = True,
    http_request=None,
) -> CreateResult:
    """One request per obligation for the period. An obligation that already has a request
    in the period is skipped and reported, never duplicated."""
    _require_admin(actor)
    if not period.is_open:
        raise ValidationError(f"{period} is closed.")
    result = CreateResult()
    existing = set(
        EvidenceRequest.objects.filter(period=period, obligation__in=obligations).values_list(
            "obligation_id", flat=True
        )
    )
    for ob in obligations:
        if ob.pk in existing:
            result.skipped.append(f"{ob.obligation_id} already has a request in {period}.")
            continue
        dept = department or ob.primary_department
        if officer and officer.department_id != dept.pk:
            raise ValidationError(
                f"{officer.full_name} is not in {dept.name}, the department for {ob.obligation_id}."
            )
        req = EvidenceRequest(
            obligation=ob,
            period=period,
            assigned_department=dept,
            assigned_officer=officer,
            due_date=due_date,
            message=message,
            evidence_required=evidence_required.strip() or ob.evidence_required,
            escalate_gm_after_days=escalate_gm_after_days,
            status=S.DRAFT,
        )
        req.stamp(actor)
        req.save()
        record(
            Action.REQUEST_CREATED,
            actor=actor,
            obj=req,
            request=http_request,
            detail=f"Request created for {dept.name}, due {due_date:%d %b %Y}.",
        )
        for f in files or []:
            f.content.seek(0)
            copy = CleanFile(
                content=type(f.content)(f.content.read(), name=f.content.name),
                original_filename=f.original_filename,
                content_type=f.content_type,
                size_bytes=f.size_bytes,
                sha256=f.sha256,
            )
            add_request_attachment(req, None, actor, clean=copy, http_request=http_request)
        if issue_now:
            issue_request(req, actor, http_request=http_request)
        result.created.append(req)
    return result


@transaction.atomic
def issue_request(req: EvidenceRequest, actor: User, *, http_request=None) -> EvidenceRequest:
    _require_admin(actor)
    req.assert_editable()
    req.transition_to(S.AWAITING)
    req.issued_at = timezone.now()
    req.stamp(actor)
    req.save()
    record(
        Action.REQUEST_ISSUED,
        actor=actor,
        obj=req,
        request=http_request,
        detail=f"Issued to {req.assigned_department.name}"
        f"{' (' + req.assigned_officer.full_name + ')' if req.assigned_officer else ''}, "
        f"due {req.due_date:%d %b %Y}.",
    )
    notices.queue_event_notice(OutboxKind.REQUEST, req)
    return req


# --- admin changes to a live request ----------------------------------------------------
@transaction.atomic
def change_deadline(
    req: EvidenceRequest, new_date: date, reason: str, actor: User, *, http_request=None
) -> EvidenceRequest:
    _require_admin(actor)
    req.assert_editable()
    reason = _require_reason(reason, "Changing a deadline")
    if not req.is_open:
        raise ValidationError("The request is closed; its deadline can no longer change.")
    old = req.due_date
    if new_date == old:
        raise ValidationError("The new deadline is the same as the current one.")
    req.due_date = new_date
    req.stamp(actor)
    req.save()
    notices.cancel_pending(req)
    record(
        Action.DEADLINE_CHANGED,
        actor=actor,
        obj=req,
        request=http_request,
        detail=f"Deadline changed from {old:%d %b %Y} to {new_date:%d %b %Y}. Reason: {reason}",
    )
    return req


@transaction.atomic
def reassign(
    req: EvidenceRequest,
    department: Department,
    officer: User | None,
    reason: str,
    actor: User,
    *,
    http_request=None,
) -> EvidenceRequest:
    _require_admin(actor)
    req.assert_editable()
    reason = _require_reason(reason, "Reassigning a request")
    if not req.is_open:
        raise ValidationError("The request is closed and cannot be reassigned.")
    if officer and officer.department_id != department.pk:
        raise ValidationError(f"{officer.full_name} is not in {department.name}.")
    if not department.is_active:
        raise ValidationError(f"{department.name} is deactivated.")
    before = f"{req.assigned_department.name} / " + (
        req.assigned_officer.full_name if req.assigned_officer else "no named officer"
    )
    req.assigned_department = department
    req.assigned_officer = officer
    req.stamp(actor)
    req.save()
    after = f"{department.name} / " + (officer.full_name if officer else "no named officer")
    record(
        Action.REQUEST_REASSIGNED,
        actor=actor,
        obj=req,
        request=http_request,
        detail=f"Reassigned from {before} to {after}. Reason: {reason}",
    )
    return req


@transaction.atomic
def close_not_applicable(
    req: EvidenceRequest, justification: str, actor: User, *, http_request=None
) -> EvidenceRequest:
    _require_admin(actor)
    req.assert_editable()
    justification = _require_reason(justification, "Closing as not applicable")
    req.transition_to(S.CLOSED_NA)
    req.closed_at = timezone.now()
    req.closure_justification = justification
    req.stamp(actor)
    req.save()
    notices.cancel_pending(req)
    record(
        Action.REQUEST_CLOSED_NA,
        actor=actor,
        obj=req,
        request=http_request,
        detail=f"Closed as not applicable. Justification: {justification}",
    )
    return req


# --- submitting -------------------------------------------------------------------------
@transaction.atomic
def submit(
    req: EvidenceRequest,
    actor: User,
    data: dict,
    files: list[CleanFile],
    *,
    http_request=None,
    submitted_at=None,
) -> Submission:
    """An officer's response. Enforces SPEC 4 rules 1-3 and 7."""
    if not req.can_submit(actor):
        if actor.role == Role.OFFICER and actor.department_id != req.assigned_department_id:
            raise PermissionDenied
        req.assert_editable()
        raise ValidationError(
            f"This request is {req.get_status_display().lower()} and cannot take a submission."
        )
    sub = Submission(
        request=req, submitted_by=actor, submitted_at=submitted_at or timezone.now(), **data
    )
    sub.stamp(actor)
    sub.full_clean(exclude=["request", "submitted_by"])
    if sub.evidence_available != EvidenceAvailable.NO and not files:
        raise ValidationError(
            {
                "files": "Attach at least one file, or set Evidence available to No and explain "
                "why in the evidence description."
            }
        )
    req.submissions.filter(is_current=True).update(is_current=False)
    sub.is_current = True
    sub.save()
    for clean in files:
        att = SubmissionAttachment(
            submission=sub,
            original_filename=clean.original_filename,
            content_type=clean.content_type,
            size_bytes=clean.size_bytes,
            sha256=clean.sha256,
            uploaded_by=actor,
        )
        att.file.save(clean.content.name, clean.content, save=False)
        att.save()
        record(
            Action.FILE_UPLOADED,
            actor=actor,
            obj=att,
            request=http_request,
            detail=f"Evidence {att.original_filename} ({att.size_bytes} bytes, "
            f"sha256 {att.sha256}).",
        )
    late = req.status == S.OVERDUE
    req.transition_to(S.SUBMITTED)
    req.stamp(actor)
    req.save()
    notices.cancel_pending(req)  # SPEC 4.7
    record(
        Action.SUBMISSION_CREATED,
        actor=actor,
        obj=sub,
        request=http_request,
        detail=f"Submitted{' late' if late else ''}: {sub.get_compliance_status_display()}, "
        f"evidence {sub.get_evidence_available_display().lower()}, "
        f"{len(files)} file(s).",
    )
    notices.queue_event_notice(OutboxKind.RECEIVED, req, submitter=actor)
    return sub


# --- verification -----------------------------------------------------------------------
def _current_for_verification(sub: Submission) -> EvidenceRequest:
    req = sub.request
    req.assert_editable()
    if not sub.is_current or req.status != S.SUBMITTED:
        raise ValidationError(
            "Only the current submission of a submitted request can be verified or returned."
        )
    return req


@transaction.atomic
def verify(sub: Submission, actor: User, comment: str = "", *, http_request=None) -> Submission:
    _require_admin(actor)  # SPEC 2 rule 2: an officer can never verify
    req = _current_for_verification(sub)
    req.transition_to(S.VERIFIED)
    now = timezone.now()
    req.closed_at = now
    req.stamp(actor)
    req.save()
    sub.verified_by = actor
    sub.verified_at = now
    sub.verification_outcome = VerificationOutcome.VERIFIED
    sub.verification_comment = (comment or "").strip()
    sub.stamp(actor)
    sub.save()
    notices.cancel_pending(req)  # SPEC 4.5
    record(
        Action.SUBMISSION_VERIFIED,
        actor=actor,
        obj=sub,
        request=http_request,
        detail=f"Verified as {sub.get_compliance_status_display()}."
        + (f" Comment: {sub.verification_comment}" if sub.verification_comment else ""),
    )
    notices.queue_event_notice(OutboxKind.VERIFIED, req)
    return sub


@transaction.atomic
def return_submission(
    sub: Submission, actor: User, comment: str, *, http_request=None
) -> Submission:
    _require_admin(actor)
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError({"verification_comment": "Say why the submission is returned."})
    req = _current_for_verification(sub)
    req.transition_to(S.RETURNED)
    req.stamp(actor)
    req.save()
    sub.verified_by = actor
    sub.verified_at = timezone.now()
    sub.verification_outcome = VerificationOutcome.RETURNED
    sub.verification_comment = comment
    sub.stamp(actor)
    sub.save()
    # SPEC 4.6: the reminder series restarts from today. Pending notices go; the daily
    # command anchors the next series on the return date (notices.returned_on).
    notices.cancel_pending(req)
    record(
        Action.SUBMISSION_RETURNED,
        actor=actor,
        obj=sub,
        request=http_request,
        detail=f"Returned. Reason: {comment}",
    )
    notices.queue_event_notice(OutboxKind.RETURNED, req, reason=comment)
    return sub
