from django.conf import settings
from django.db import models

from apps.core.models import TrackedModel


class DepartmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Department(TrackedModel):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    gm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="departments_led",
    )
    is_active = models.BooleanField(default=True)

    objects = DepartmentQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.code = (self.code or "").upper()
        super().save(*args, **kwargs)

    def gm_users(self):
        """Everyone who should be copied as GM: the named GM and any member flagged as GM."""
        from apps.accounts.models import User

        ids = set(
            User.objects.filter(department=self, is_department_gm=True, is_active=True).values_list(
                "pk", flat=True
            )
        )
        if self.gm_id and self.gm.is_active:
            ids.add(self.gm_id)
        return User.objects.filter(pk__in=ids)
