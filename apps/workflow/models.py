from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TrackedModel

from .storage import private_storage, request_attachment_path, submission_attachment_path


class InvalidTransition(Exception):
    pass


class ReadOnlyPeriod(Exception):
    """SPEC 4.8: a request in a closed reporting period is read-only for everyone."""


class ReportingPeriod(TrackedModel):
    name = models.CharField(max_length=50, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_open = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            # Exactly one open period, enforced by the database as well as clean().
            models.UniqueConstraint(
                fields=["is_open"], condition=Q(is_open=True), name="one_open_period"
            )
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({"end_date": "The period ends before it starts."})
        if self.is_open:
            others = ReportingPeriod.objects.filter(is_open=True).exclude(pk=self.pk)
            if others.exists():
                raise ValidationError(
                    f"Only one reporting period may be open. Close {others.first()} first."
                )

    @classmethod
    def current(cls) -> "ReportingPeriod | None":
        return cls.objects.filter(is_open=True).first()


class RequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    AWAITING = "AWAITING", "Awaiting evidence"
    SUBMITTED = "SUBMITTED", "Submitted"
    OVERDUE = "OVERDUE", "Overdue"
    RETURNED = "RETURNED", "Returned"
    VERIFIED = "VERIFIED", "Verified"
    CLOSED_NA = "CLOSED_NA", "Closed – not applicable"


S = RequestStatus

# SPEC 3: the only transitions allowed. Anything not listed raises InvalidTransition.
TRANSITIONS: dict[str, frozenset[str]] = {
    S.DRAFT: frozenset({S.AWAITING}),
    S.AWAITING: frozenset({S.SUBMITTED, S.OVERDUE}),
    S.OVERDUE: frozenset({S.SUBMITTED}),
    S.SUBMITTED: frozenset({S.VERIFIED, S.RETURNED}),
    S.RETURNED: frozenset({S.SUBMITTED, S.OVERDUE}),
    S.VERIFIED: frozenset(),
    S.CLOSED_NA: frozenset(),
}
# "any -> CLOSED_NA": every other state may be closed as not applicable.
for _state in TRANSITIONS:
    if _state != S.CLOSED_NA:
        TRANSITIONS[_state] = TRANSITIONS[_state] | {S.CLOSED_NA}

OPEN_STATUSES = (S.DRAFT, S.AWAITING, S.SUBMITTED, S.OVERDUE, S.RETURNED)
AWAITING_OFFICER = (S.AWAITING, S.OVERDUE, S.RETURNED)
VISIBLE_TO_OFFICER = (S.AWAITING, S.SUBMITTED, S.OVERDUE, S.RETURNED, S.VERIFIED, S.CLOSED_NA)

STATUS_CSS = {
    S.DRAFT: "accent",
    S.AWAITING: "warn",
    S.SUBMITTED: "review",
    S.OVERDUE: "bad",
    S.RETURNED: "bad",
    S.VERIFIED: "ok",
    S.CLOSED_NA: "na",
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


class EvidenceRequestQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def visible_to(self, user):
        """Row-level scoping. Admins and executives see everything; officers see their
        own department's issued requests and nothing else."""
        if user.role in ("ADMIN", "EXECUTIVE"):
            return self
        if user.role == "OFFICER" and user.department_id:
            return self.filter(
                assigned_department_id=user.department_id, status__in=VISIBLE_TO_OFFICER
            )
        return self.none()

    def with_related(self):
        return self.select_related(
            "obligation",
            "obligation__instrument",
            "period",
            "assigned_department",
            "assigned_officer",
        )


class EvidenceRequest(TrackedModel):
    obligation = models.ForeignKey(
        "obligations.Obligation", on_delete=models.PROTECT, related_name="requests"
    )
    period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="requests")
    assigned_department = models.ForeignKey(
        "organisation.Department", on_delete=models.PROTECT, related_name="requests"
    )
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_requests",
    )
    due_date = models.DateField()
    message = models.TextField(blank=True)
    evidence_required = models.TextField()
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=S.DRAFT, db_index=True
    )
    escalate_gm_after_days = models.IntegerField(default=5)
    escalated_to_gm_at = models.DateTimeField(null=True, blank=True)
    escalated_to_management_at = models.DateTimeField(null=True, blank=True)
    reminders_sent = models.IntegerField(default=0)
    issued_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_justification = models.TextField(blank=True)

    objects = EvidenceRequestQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "obligation__obligation_id"]
        unique_together = [("obligation", "period")]

    def __str__(self) -> str:
        return f"{self.obligation.obligation_id} · {self.period.name}"

    # --- state -------------------------------------------------------------------------
    def transition_to(self, new_status: str) -> None:
        """The single place a request's status changes. Services call this; views never
        assign status directly."""
        if not can_transition(self.status, new_status):
            raise InvalidTransition(f"A request cannot move from {self.status} to {new_status}.")
        self.status = new_status

    def assert_editable(self) -> None:
        if not self.period.is_open:
            raise ReadOnlyPeriod(
                f"{self.period.name} is closed. Its requests are read-only for everyone."
            )

    @property
    def is_editable(self) -> bool:
        return self.period.is_open

    @property
    def status_css(self) -> str:
        return STATUS_CSS.get(self.status, "na")

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def awaiting_officer(self) -> bool:
        return self.status in AWAITING_OFFICER

    # --- access ------------------------------------------------------------------------
    def is_visible_to(self, user) -> bool:
        if user.role in ("ADMIN", "EXECUTIVE"):
            return True
        return (
            user.role == "OFFICER"
            and user.department_id is not None
            and user.department_id == self.assigned_department_id
            and self.status in VISIBLE_TO_OFFICER
        )

    def can_submit(self, user) -> bool:
        return (
            user.role == "OFFICER"
            and user.department_id == self.assigned_department_id
            and self.status in AWAITING_OFFICER
            and self.is_editable
        )

    # --- dates -------------------------------------------------------------------------
    def days_remaining(self, today=None) -> int:
        today = today or timezone.localdate()
        return (self.due_date - today).days

    @property
    def days_overdue(self) -> int:
        return max(0, -self.days_remaining())

    @property
    def current_submission(self) -> "Submission | None":
        cached = getattr(self, "_prefetched_objects_cache", {}).get("submissions")
        if cached is not None:
            return next((s for s in cached if s.is_current), None)
        return self.submissions.filter(is_current=True).first()


class ComplianceStatus(models.TextChoices):
    COMPLIANT = "COMPLIANT", "Compliant"
    PARTIALLY_COMPLIANT = "PARTIALLY_COMPLIANT", "Partially compliant"
    NON_COMPLIANT = "NON_COMPLIANT", "Non-compliant"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"


COMPLIANCE_CSS = {
    "COMPLIANT": "ok",
    "PARTIALLY_COMPLIANT": "warn",
    "NON_COMPLIANT": "bad",
    "NOT_APPLICABLE": "na",
    "UNDER_REVIEW": "review",
}


class EvidenceAvailable(models.TextChoices):
    YES = "YES", "Yes"
    NO = "NO", "No"
    PARTIAL = "PARTIAL", "Partial"


class VerificationOutcome(models.TextChoices):
    VERIFIED = "VERIFIED", "Verified"
    RETURNED = "RETURNED", "Returned"


ACTION_PLAN_MAX_DAYS = 30


class Submission(TrackedModel):
    request = models.ForeignKey(
        EvidenceRequest, on_delete=models.PROTECT, related_name="submissions"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submissions"
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    compliance_status = models.CharField(max_length=30, choices=ComplianceStatus.choices)
    evidence_available = models.CharField(max_length=10, choices=EvidenceAvailable.choices)
    evidence_description = models.TextField()
    date_of_last_review = models.DateField(null=True, blank=True)
    next_review_due = models.DateField(null=True, blank=True)
    action_required = models.TextField(blank=True)
    action_owner = models.CharField(max_length=200, blank=True)
    target_resolution_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    is_current = models.BooleanField(default=True)

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="verified_submissions",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_outcome = models.CharField(
        max_length=10, null=True, blank=True, choices=VerificationOutcome.choices
    )
    verification_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"Submission for {self.request} at {self.submitted_at:%Y-%m-%d %H:%M}"

    @property
    def compliance_css(self) -> str:
        return COMPLIANCE_CSS.get(self.compliance_status, "na")

    def clean(self) -> None:
        """SPEC 4, rules 1 and 2. Rule 3 (attachments) is checked by the submit service,
        because attachments are saved after the submission row exists."""
        errors: dict[str, str] = {}
        if self.compliance_status in (
            ComplianceStatus.PARTIALLY_COMPLIANT,
            ComplianceStatus.NON_COMPLIANT,
        ):
            if not (self.action_required or "").strip():
                errors["action_required"] = "Describe the action required."
            if not (self.action_owner or "").strip():
                errors["action_owner"] = "Name who owns the action."
            if not self.target_resolution_date:
                errors["target_resolution_date"] = "Set a target resolution date."
            else:
                submitted_on = timezone.localdate(self.submitted_at or timezone.now())
                if self.target_resolution_date > submitted_on + timedelta(
                    days=ACTION_PLAN_MAX_DAYS
                ):
                    errors["target_resolution_date"] = (
                        f"The target date must be no more than {ACTION_PLAN_MAX_DAYS} days "
                        f"after the submission date ({submitted_on:%d %b %Y})."
                    )
        if (
            self.compliance_status == ComplianceStatus.NOT_APPLICABLE
            and not (self.remarks or "").strip()
        ):
            errors["remarks"] = "Give the justification for Not applicable in the remarks."
        if (
            self.evidence_available == EvidenceAvailable.NO
            and not (self.evidence_description or "").strip()
        ):
            errors["evidence_description"] = "Explain why no evidence is available."
        if errors:
            raise ValidationError(errors)


class AttachmentBase(models.Model):
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return self.original_filename


class RequestAttachment(AttachmentBase):
    request = models.ForeignKey(
        EvidenceRequest, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(
        upload_to=request_attachment_path, storage=private_storage, max_length=500
    )

    class Meta(AttachmentBase.Meta):
        pass

    @property
    def owning_request(self) -> EvidenceRequest:
        return self.request


class SubmissionAttachment(AttachmentBase):
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="attachments")
    file = models.FileField(
        upload_to=submission_attachment_path, storage=private_storage, max_length=500
    )

    class Meta(AttachmentBase.Meta):
        pass

    @property
    def owning_request(self) -> EvidenceRequest:
        return self.submission.request
