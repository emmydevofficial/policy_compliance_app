from django.conf import settings
from django.db import models


class AuditImmutable(Exception):
    pass


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditImmutable("Audit events cannot be updated.")

    def delete(self):
        raise AuditImmutable("Audit events cannot be deleted.")

    def bulk_update(self, *args, **kwargs):
        raise AuditImmutable("Audit events cannot be updated.")

    def update_or_create(self, *args, **kwargs):
        raise AuditImmutable("Audit events cannot be updated.")


class AuditEvent(models.Model):
    """Append-only. No update, no delete, anywhere in the codebase."""

    occurred_at = models.DateTimeField(db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=60)
    obligation_ref = models.CharField(max_length=30, blank=True, db_index=True)
    detail = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        db_table = "audit_event"

    def __str__(self) -> str:
        return f"{self.occurred_at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise AuditImmutable("Audit events cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutable("Audit events cannot be deleted.")

    @property
    def actor_label(self) -> str:
        return self.actor.full_name if self.actor_id else "System"
