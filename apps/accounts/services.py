"""Account actions: invitations and activation, sign-in bookkeeping, preferences."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.auditlog.services import Action, record
from apps.core.ratelimit import client_ip

from .models import Invitation, NotificationPreference, User

security_log = logging.getLogger("obligation_desk.security")


def send_invitation(user: User, actor: User | None, *, http_request=None) -> Invitation:
    """A single-use activation link, valid for INVITATION_VALID_HOURS. The person sets their
    own password; the ADMIN never sees or sets it."""
    from apps.notifications.services import _guard_real_email

    # Any earlier unused link stops working when a new one is issued.
    Invitation.objects.filter(user=user, used_at__isnull=True).update(expires_at=timezone.now())
    inv, raw = Invitation.issue(user, created_by=actor)
    link = settings.SITE_URL.rstrip("/") + reverse("accounts:activate", args=[raw])
    ctx = {"user": user, "link": link, "hours": settings.INVITATION_VALID_HOURS}
    subject = "Your Obligation Desk account"
    body = render_to_string("emails/invitation.txt", ctx)
    _guard_real_email()
    msg = EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
    transaction.on_commit(lambda: msg.send(fail_silently=True))
    record(
        Action.USER_INVITED,
        actor=actor,
        obj=user,
        request=http_request,
        detail=f"Activation link sent to {user.email}, valid "
        f"{settings.INVITATION_VALID_HOURS} hours.",
    )
    return inv


@transaction.atomic
def activate(inv: Invitation, password: str, *, http_request=None) -> User:
    user = inv.user
    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])
    inv.used_at = timezone.now()
    inv.save(update_fields=["used_at"])
    NotificationPreference.objects.get_or_create(user=user)
    record(
        Action.ACCOUNT_ACTIVATED,
        actor=user,
        obj=user,
        request=http_request,
        detail="Account activated through the invitation link.",
    )
    return user


def signed_in(user: User, http_request) -> None:
    ip = client_ip(http_request)
    user.last_login_ip = ip
    user.save(update_fields=["last_login_ip"])
    record(Action.SIGN_IN, actor=user, obj=user, request=http_request, detail="Signed in.")


def sign_in_failed(email: str, http_request, reason: str = "bad credentials") -> None:
    ip = client_ip(http_request)
    security_log.warning("Authentication failure for %r from %s (%s)", email, ip, reason)
    user = User.objects.filter(email__iexact=email).first() if email else None
    record(
        Action.SIGN_IN_FAILED,
        actor=None,
        object_type="User",
        object_id=str(user.pk) if user else "",
        request=http_request,
        detail=f"Sign-in failed for {email or '(blank)'}: {reason}.",
    )


def save_preferences(user: User, prefs: NotificationPreference, *, http_request=None) -> None:
    prefs.stamp(user)
    prefs.save()
    user.stamp(user)
    user.full_clean()
    user.save()
    record(
        Action.PREFERENCES_CHANGED,
        actor=user,
        obj=user,
        request=http_request,
        detail="Contact details, notice preferences or delegation updated.",
    )
