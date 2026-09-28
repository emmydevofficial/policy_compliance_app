import hashlib
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TrackedModel


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin (GM, Regulation & Compliance)"
    OFFICER = "OFFICER", "Officer"
    EXECUTIVE = "EXECUTIVE", "Executive Management"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("full_name", email)
        return self._create_user(email, password, **extra)

    def active(self):
        return self.filter(is_active=True)


class User(AbstractBaseUser, PermissionsMixin, TrackedModel):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    job_title = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, db_index=True)
    department = models.ForeignKey(
        "organisation.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="members",
    )
    is_department_gm = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False, help_text="Can sign in to the Django admin site (technical staff only)."
    )
    delegate_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="delegations"
    )
    delegate_from = models.DateField(null=True, blank=True)
    delegate_until = models.DateField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    def clean(self) -> None:
        super().clean()
        self.email = (self.email or "").lower()
        if self.role == Role.OFFICER and not self.department_id:
            raise ValidationError({"department": "An officer must belong to a department."})
        if self.role in (Role.ADMIN, Role.EXECUTIVE) and self.department_id:
            raise ValidationError(
                {"department": "Admin and Executive users must not have a department."}
            )
        if self.is_department_gm and self.role != Role.OFFICER:
            raise ValidationError(
                {"is_department_gm": "Only a user with the Officer role can be a department GM."}
            )
        if self.delegate_to_id and self.delegate_to_id == self.pk:
            raise ValidationError({"delegate_to": "You cannot delegate to yourself."})
        if bool(self.delegate_from) != bool(self.delegate_until):
            raise ValidationError("Give both a start and an end date for the delegation.")
        if self.delegate_from and self.delegate_until and self.delegate_from > self.delegate_until:
            raise ValidationError({"delegate_until": "The end date is before the start date."})
        if self.delegate_from and not self.delegate_to_id:
            raise ValidationError({"delegate_to": "Choose who covers for you."})

    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.full_name.split(" ")[0] if self.full_name else self.email

    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_officer(self) -> bool:
        return self.role == Role.OFFICER

    @property
    def is_executive(self) -> bool:
        return self.role == Role.EXECUTIVE

    def active_delegate(self, on: date | None = None):
        """The user covering for this one on the given day, if any."""
        on = on or timezone.localdate()
        if (
            self.delegate_to_id
            and self.delegate_from
            and self.delegate_until
            and self.delegate_from <= on <= self.delegate_until
            and self.delegate_to.is_active
        ):
            return self.delegate_to
        return None


class NotificationPreference(TrackedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs"
    )
    new_request = models.BooleanField(default=True)
    deadline_reminders = models.BooleanField(
        default=True, help_text="Reminders for Medium and Low risk obligations."
    )
    high_risk_deadline_reminders = models.BooleanField(
        default=True,
        editable=False,
        help_text="Always on. Reminders for High risk obligations cannot be disabled.",
    )
    sms_when_overdue = models.BooleanField(default=False)
    outcome_notices = models.BooleanField(default=True)
    weekly_digest = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"Notification preferences for {self.user}"

    def save(self, *args, **kwargs) -> None:
        # SPEC 3: deadline reminders for High risk obligations cannot be disabled, whatever
        # a form or a script sets.
        self.high_risk_deadline_reminders = True
        super().save(*args, **kwargs)

    def wants(self, kind: str, *, high_risk: bool = False) -> bool:
        if kind in ("REMINDER", "FINAL", "OVERDUE"):
            return self.high_risk_deadline_reminders if high_risk else self.deadline_reminders
        if kind == "REQUEST":
            return self.new_request
        if kind in ("RECEIVED", "RETURNED", "VERIFIED"):
            return self.outcome_notices
        if kind == "DIGEST":
            return self.weekly_digest
        return True


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class InvitationQuerySet(models.QuerySet):
    def usable(self):
        return self.filter(used_at__isnull=True, expires_at__gt=timezone.now())


class Invitation(models.Model):
    """A single-use activation link. Only the hash of the token is stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invitations"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation for {self.user}"

    @classmethod
    def issue(cls, user, created_by=None) -> tuple["Invitation", str]:
        raw = secrets.token_urlsafe(32)
        inv = cls.objects.create(
            user=user,
            token_hash=_hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=settings.INVITATION_VALID_HOURS),
            created_by=created_by,
        )
        return inv, raw

    @classmethod
    def find_usable(cls, raw: str) -> "Invitation | None":
        return (
            cls.objects.usable().select_related("user").filter(token_hash=_hash_token(raw)).first()
        )
