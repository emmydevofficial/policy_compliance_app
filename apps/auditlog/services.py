"""Writing audit events. Called from the service function that performs each action."""

from django.utils import timezone

from apps.core.ratelimit import client_ip

from .models import AuditEvent


class Action:
    SIGN_IN = "sign_in"
    SIGN_IN_FAILED = "sign_in_failed"
    SIGN_OUT = "sign_out"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    ACCOUNT_ACTIVATED = "account_activated"
    REQUEST_CREATED = "request_created"
    REQUEST_ISSUED = "request_issued"
    DEADLINE_CHANGED = "deadline_changed"
    REQUEST_REASSIGNED = "request_reassigned"
    REQUEST_CLOSED_NA = "request_closed_na"
    REQUEST_OVERDUE = "request_overdue"
    SUBMISSION_CREATED = "submission_created"
    SUBMISSION_VERIFIED = "submission_verified"
    SUBMISSION_RETURNED = "submission_returned"
    OBLIGATION_CREATED = "obligation_created"
    OBLIGATION_UPDATED = "obligation_updated"
    OBLIGATION_DEACTIVATED = "obligation_deactivated"
    DEPARTMENT_CREATED = "department_created"
    DEPARTMENT_UPDATED = "department_updated"
    DEPARTMENT_DEACTIVATED = "department_deactivated"
    DEPARTMENT_REACTIVATED = "department_reactivated"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"
    USER_INVITED = "user_invited"
    ROLE_CHANGED = "role_changed"
    PEOPLE_IMPORTED = "people_imported"
    FILE_UPLOADED = "file_uploaded"
    FILE_DOWNLOADED = "file_downloaded"
    FILE_REJECTED = "file_rejected"
    REMINDER_RULE_CHANGED = "reminder_rule_changed"
    TEMPLATE_EDITED = "template_edited"
    EXPORT_GENERATED = "export_generated"
    PREFERENCES_CHANGED = "preferences_changed"
    PERIOD_CHANGED = "period_changed"
    NOTICE_ESCALATED = "notice_escalated"


def record(
    action: str,
    *,
    actor=None,
    obj=None,
    object_type: str = "",
    object_id: str = "",
    obligation_ref: str = "",
    detail: str = "",
    request=None,
) -> AuditEvent:
    """Append one audit event. `request` is the HTTP request, for address and user agent."""
    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id or str(obj.pk)
        if not obligation_ref:
            obligation_ref = _obligation_ref_for(obj)
    ip = None
    agent = ""
    if request is not None:
        ip = client_ip(request)
        agent = (request.META.get("HTTP_USER_AGENT") or "")[:255]
        if actor is None and getattr(request, "user", None) and request.user.is_authenticated:
            actor = request.user
    return AuditEvent.objects.create(
        occurred_at=timezone.now(),
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        action=action,
        object_type=object_type,
        object_id=object_id,
        obligation_ref=obligation_ref,
        detail=detail,
        ip_address=ip,
        user_agent=agent,
    )


def _obligation_ref_for(obj) -> str:
    name = obj.__class__.__name__
    try:
        if name == "Obligation":
            return obj.obligation_id
        if name == "EvidenceRequest":
            return obj.obligation.obligation_id
        if name == "Submission":
            return obj.request.obligation.obligation_id
        if name == "RequestAttachment":
            return obj.request.obligation.obligation_id
        if name == "SubmissionAttachment":
            return obj.submission.request.obligation.obligation_id
    except AttributeError:
        return ""
    return ""
