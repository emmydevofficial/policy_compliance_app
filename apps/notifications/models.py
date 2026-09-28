from datetime import time

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TrackedModel


class TemplateKey(models.TextChoices):
    EVIDENCE_REQUEST = "evidence_request", "Evidence request issued"
    REMINDER_BEFORE = "reminder_before", "Reminder before the deadline"
    FINAL_NOTICE = "final_notice", "Final notice on the deadline"
    OVERDUE_NOTICE = "overdue_notice", "Overdue notice"
    ESCALATION_GM = "escalation_gm", "Escalation to department GM"
    ESCALATION_MANAGEMENT = "escalation_management", "Escalation to Executive Management"
    SUBMISSION_RECEIVED = "submission_received", "Submission received"
    SUBMISSION_RETURNED = "submission_returned", "Submission returned"
    SUBMISSION_VERIFIED = "submission_verified", "Submission verified"
    WEEKLY_DIGEST = "weekly_digest", "Weekly digest"


class NotificationTemplate(TrackedModel):
    key = models.CharField(max_length=50, unique=True, choices=TemplateKey.choices)
    name = models.CharField(max_length=200)
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        from .rendering import validate_template

        errors = {}
        for field in ("subject_template", "body_template"):
            problem = validate_template(getattr(self, field))
            if problem:
                errors[field] = problem
        if errors:
            raise ValidationError(errors)


def default_days_before() -> list[int]:
    return [14, 7, 3, 1]


class ReminderRule(TrackedModel):
    """A single settings row. Use ReminderRule.get()."""

    days_before = models.JSONField(default=default_days_before)
    send_on_due_date = models.BooleanField(default=True)
    repeat_every_working_days = models.IntegerField(default=2)
    stop_after_count = models.IntegerField(null=True, blank=True)
    escalate_gm_after_days = models.IntegerField(default=5)
    escalate_management_after_days = models.IntegerField(default=15)
    escalate_management_high_risk_only = models.BooleanField(default=True)
    send_time = models.TimeField(default=time(8, 0))
    working_days_only = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    in_app_enabled = models.BooleanField(default=True)

    def __str__(self) -> str:
        return "Reminder rule"

    def clean(self) -> None:
        days = self.days_before
        if not isinstance(days, list) or not all(isinstance(d, int) and d > 0 for d in days):
            raise ValidationError({"days_before": "Give whole numbers of days, above zero."})
        if self.repeat_every_working_days < 1:
            raise ValidationError({"repeat_every_working_days": "Must be at least 1."})
        if self.escalate_management_after_days <= self.escalate_gm_after_days:
            raise ValidationError(
                {
                    "escalate_management_after_days": (
                        "Management escalation must come after the GM escalation."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        self.days_before = sorted({int(d) for d in self.days_before}, reverse=True)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The reminder rule cannot be deleted.")

    @classmethod
    def get(cls) -> "ReminderRule":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Holiday(TrackedModel):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date:%d %b %Y} – {self.name}"


class OutboxKind(models.TextChoices):
    REQUEST = "REQUEST", "Request issued"
    REMINDER = "REMINDER", "Reminder"
    FINAL = "FINAL", "Final notice"
    OVERDUE = "OVERDUE", "Overdue notice"
    ESCALATION_GM = "ESCALATION_GM", "Escalation to GM"
    ESCALATION_MGMT = "ESCALATION_MGMT", "Escalation to management"
    RECEIVED = "RECEIVED", "Submission received"
    RETURNED = "RETURNED", "Submission returned"
    VERIFIED = "VERIFIED", "Submission verified"
    DIGEST = "DIGEST", "Digest"


class OutboxStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


MAX_SEND_ATTEMPTS = 5
SCHEDULED_KINDS = ["REMINDER", "FINAL", "OVERDUE", "ESCALATION_GM", "ESCALATION_MGMT"]


class NotificationOutbox(models.Model):
    """Every notice, before it is sent. Both the delivery queue and the record of what was
    sent: subject and body are stored rendered, so later template edits never change them."""

    request = models.ForeignKey(
        "workflow.EvidenceRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outbox",
    )
    recipient = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    recipient_email = models.EmailField()
    cc_emails = models.JSONField(default=list, blank=True)
    template_key = models.CharField(max_length=50)
    kind = models.CharField(max_length=20, choices=OutboxKind.choices, db_index=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    body_html = models.TextField(blank=True)
    scheduled_for = models.DateTimeField(db_index=True)
    scheduled_date = models.DateField(help_text="The Lagos calendar day this notice belongs to.")
    status = models.CharField(
        max_length=10, choices=OutboxStatus.choices, default=OutboxStatus.PENDING, db_index=True
    )
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reported_in_digest = models.BooleanField(default=False)

    class Meta:
        ordering = ["-scheduled_for"]
        verbose_name = "outbox notice"
        constraints = [
            # SPEC 8: for the scheduled notices the daily command creates, (request, kind,
            # scheduled date) is unique. Event notices (issued, received, returned, verified)
            # are not deduplicated: two returns on one day are two real events.
            models.UniqueConstraint(
                fields=["request", "kind", "scheduled_date"],
                condition=Q(request__isnull=False, kind__in=SCHEDULED_KINDS),
                name="outbox_unique_request_kind_day",
            ),
            # Digests are not tied to a request: unique per recipient, kind and day.
            models.UniqueConstraint(
                fields=["recipient_email", "kind", "scheduled_date"],
                condition=Q(request__isnull=True),
                name="outbox_unique_digest_recipient_day",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} to {self.recipient_email} ({self.status})"
