from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import Invitation, Role, User
from apps.auditlog.models import AuditEvent
from apps.core.tests.factories import PASSWORD, DepartmentFactory


def test_officer_requires_department(db):
    u = User(email="x@example.org", full_name="X", role=Role.OFFICER)
    with pytest.raises(ValidationError):
        u.full_clean(exclude=["password"])


@pytest.mark.parametrize("role", [Role.ADMIN, Role.EXECUTIVE])
def test_admin_and_executive_must_not_have_department(db, role):
    u = User(email="x@example.org", full_name="X", role=role, department=DepartmentFactory())
    with pytest.raises(ValidationError):
        u.full_clean(exclude=["password"])


def test_sign_in_records_audit_and_address(client, officer_a):
    r = client.post(
        reverse("accounts:login"),
        {"username": officer_a.email, "password": PASSWORD},
        REMOTE_ADDR="10.1.2.3",
    )
    assert r.status_code == 302
    officer_a.refresh_from_db()
    assert officer_a.last_login_ip == "10.1.2.3"
    assert AuditEvent.objects.filter(action="sign_in", actor=officer_a).exists()


def test_sign_in_failure_is_logged_with_source_address(client, officer_a, caplog):
    client.post(
        reverse("accounts:login"),
        {"username": officer_a.email, "password": "wrong"},
        REMOTE_ADDR="10.9.9.9",
    )
    ev = AuditEvent.objects.get(action="sign_in_failed")
    assert ev.ip_address == "10.9.9.9"
    assert "10.9.9.9" in caplog.text


def test_login_is_rate_limited(client, officer_a):
    for _ in range(10):
        client.post(reverse("accounts:login"), {"username": officer_a.email, "password": "no"})
    r = client.post(reverse("accounts:login"), {"username": officer_a.email, "password": PASSWORD})
    assert r.status_code == 429


def test_password_reset_is_rate_limited(client, officer_a):
    for _ in range(5):
        client.post(reverse("accounts:password_reset"), {"email": officer_a.email})
    r = client.post(reverse("accounts:password_reset"), {"email": officer_a.email})
    assert r.status_code == 429


def test_invitation_is_single_use_and_admin_never_sets_password(
    client, admin, dept_a, django_capture_on_commit_callbacks
):
    client.force_login(admin)
    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            reverse("admin_area:person_create"),
            {
                "full_name": "New Person",
                "email": "new@example.org",
                "role": "OFFICER",
                "department": dept_a.pk,
            },
        )
    assert r.status_code == 302
    user = User.objects.get(email="new@example.org")
    assert not user.has_usable_password()
    link = next(ln for ln in mail.outbox[-1].body.splitlines() if "/activate/" in ln).strip()
    path = link.split("localhost:8000")[-1]
    client.logout()
    pw = "a-long-new-passphrase-42"
    r = client.post(path, {"new_password1": pw, "new_password2": pw})
    assert r.status_code == 302
    user.refresh_from_db()
    assert user.check_password(pw)
    assert client.get(path).status_code == 410  # used


def test_invitation_expires_after_72_hours(officer_a):
    inv, raw = Invitation.issue(officer_a)
    with freeze_time(timezone.now() + timedelta(hours=71)):
        assert Invitation.find_usable(raw)
    with freeze_time(timezone.now() + timedelta(hours=73)):
        assert Invitation.find_usable(raw) is None


def test_password_minimum_length_is_12(client, officer_a):
    client.force_login(officer_a)
    r = client.post(
        reverse("accounts:password_change"),
        {"old_password": PASSWORD, "new_password1": "Short1!xyz", "new_password2": "Short1!xyz"},
    )
    assert r.status_code == 200 and b"at least 12" in r.content


def test_executive_can_sign_out(client, executive):
    client.force_login(executive)
    assert client.post(reverse("accounts:logout")).status_code == 302


def test_officer_settings_save_delegation(client, officer_a, dept_a):
    from apps.core.tests.factories import UserFactory

    cover = UserFactory(email="cover@example.org", department=dept_a)
    client.force_login(officer_a)
    today = timezone.localdate()
    r = client.post(
        reverse("my:settings"),
        {
            "c-full_name": "Ada Officer",
            "c-job_title": "",
            "c-phone": "0800",
            "p-new_request": "on",
            "p-outcome_notices": "on",
            "d-delegate_to": cover.pk,
            "d-delegate_from": today.isoformat(),
            "d-delegate_until": (today + timedelta(days=3)).isoformat(),
        },
    )
    assert r.status_code == 302
    officer_a.refresh_from_db()
    assert officer_a.active_delegate() == cover and officer_a.phone == "0800"
    assert officer_a.notification_prefs.high_risk_deadline_reminders is True
