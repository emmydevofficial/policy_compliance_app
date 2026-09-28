from django.db import models

from apps.core.models import TrackedModel


class RegulatoryInstrument(TrackedModel):
    name = models.CharField(max_length=200, unique=True)
    short_code = models.CharField(max_length=20, unique=True)
    citation = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class RiskLevel(models.TextChoices):
    HIGH = "HIGH", "High"
    MEDIUM = "MEDIUM", "Medium"
    LOW = "LOW", "Low"


class ObligationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Obligation(TrackedModel):
    obligation_id = models.CharField(max_length=30, unique=True)
    instrument = models.ForeignKey(
        RegulatoryInstrument, on_delete=models.PROTECT, related_name="obligations"
    )
    document_reference = models.CharField(max_length=255)
    category = models.CharField(max_length=200)
    description = models.TextField()
    obligation_type = models.CharField(max_length=100, default="Mandatory")
    frequency = models.CharField(max_length=200)
    primary_department = models.ForeignKey(
        "organisation.Department", on_delete=models.PROTECT, related_name="primary_obligations"
    )
    supporting_departments = models.ManyToManyField(
        "organisation.Department", blank=True, related_name="supporting_obligations"
    )
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices, db_index=True)
    evidence_required = models.TextField()
    regulatory_deadline = models.CharField(max_length=255)
    consequence = models.TextField()
    is_active = models.BooleanField(default=True)

    objects = ObligationQuerySet.as_manager()

    class Meta:
        ordering = ["obligation_id"]

    def __str__(self) -> str:
        return self.obligation_id

    @property
    def evidence_items(self) -> list[str]:
        return [e.strip() for e in self.evidence_required.split(";") if e.strip()]

    @property
    def risk_css(self) -> str:
        return {"HIGH": "bad", "MEDIUM": "warn", "LOW": "na"}.get(self.risk_level, "na")
