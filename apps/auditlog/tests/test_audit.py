"""SPEC 3 and 14: AuditEvent is append-only."""

import pytest
from django.contrib.admin.sites import site
from django.test import RequestFactory

from apps.auditlog.models import AuditEvent, AuditImmutable
from apps.auditlog.services import record


@pytest.fixture
def event(db):
    return record("sign_in", detail="Signed in.")


def test_audit_event_cannot_be_updated(event):
    event.detail = "tampered"
    with pytest.raises(AuditImmutable):
        event.save()
    assert AuditEvent.objects.get(pk=event.pk).detail == "Signed in."


def test_audit_event_cannot_be_deleted(event):
    with pytest.raises(AuditImmutable):
        event.delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_audit_queryset_cannot_update_or_delete(event):
    with pytest.raises(AuditImmutable):
        AuditEvent.objects.filter(pk=event.pk).update(detail="x")
    with pytest.raises(AuditImmutable):
        AuditEvent.objects.all().delete()
    with pytest.raises(AuditImmutable):
        AuditEvent.objects.bulk_update([event], ["detail"])


def test_audit_log_is_read_only_in_django_admin(event, admin):
    ma = site._registry[AuditEvent]
    req = RequestFactory().get("/")
    req.user = admin
    assert not ma.has_add_permission(req)
    assert not ma.has_change_permission(req, event)
    assert not ma.has_delete_permission(req, event)


def test_audit_view_filters_by_obligation(client, admin, event):
    record(
        "obligation_created",
        object_type="Obligation",
        obligation_ref="LIC-001",
        detail="Created LIC-001.",
    )
    client.force_login(admin)
    r = client.get("/manage/audit/?obligation=LIC-001")
    assert b"Created LIC-001." in r.content and b"Signed in." not in r.content
