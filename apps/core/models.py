from django.conf import settings
from django.db import models


class TrackedModel(models.Model):
    """Who created and last changed a row, and when. For every user-editable model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True

    def stamp(self, actor) -> None:
        """Record the acting user before a save. Call from service functions."""
        if actor is not None and getattr(actor, "pk", None):
            if not self.pk:
                self.created_by = actor
            self.updated_by = actor
