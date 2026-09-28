"""SPEC 2 rules 1, 2, 5 and SPEC 14: officer in department A against department B's things."""

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.auditlog.models import AuditEvent
from apps.core.tests.helpers import good_submission
from apps.workflow import services as wf
from apps.workflow.files import SUBMISSION_TYPES, validate_upload


@pytest.fixture
def b_world(admin, officer_b, req_b, pdf_upload):
    wf.add_request_attachment(req_b, pdf_upload("circular.pdf"), admin)
    sub = wf.submit(
        req_b, officer_b, good_submission(), [validate_upload(pdf_upload(), SUBMISSION_TYPES)]
    )
    return req_b, sub


def test_officer_cannot_fetch_other_department_request(client, officer_a, b_world):
    req, _ = b_world
    client.force_login(officer_a)
    assert client.get(reverse("my:submit", args=[req.pk])).status_code == 403


def test_officer_cannot_post_submission_to_other_department_request(
    client, officer_a, b_world, pdf_upload
):
    req, _ = b_world
    client.force_login(officer_a)
    r = client.post(
        reverse("my:submit", args=[req.pk]), {**good_submission(), "files": pdf_upload()}
    )
    assert r.status_code == 403


def test_officer_cannot_download_other_department_request_attachment(client, officer_a, b_world):
    req, _ = b_world
    client.force_login(officer_a)
    att = req.attachments.first()
    assert client.get(reverse("requests:attachment_download", args=[att.pk])).status_code == 403


def test_officer_cannot_download_other_department_submission_attachment(client, officer_a, b_world):
    _, sub = b_world
    client.force_login(officer_a)
    att = sub.attachments.first()
    assert client.get(reverse("requests:evidence_download", args=[att.pk])).status_code == 403
    assert not AuditEvent.objects.filter(action="file_downloaded").exists()


def test_officer_does_not_see_other_department_submission_on_obligation_page(
    client, officer_a, b_world
):
    req, sub = b_world
    client.force_login(officer_a)
    r = client.get(reverse("obligations:detail", args=[req.obligation.obligation_id]))
    assert r.status_code == 200
    assert sub.attachments.first().original_filename.encode() not in r.content


def test_officer_can_download_own_department_file_and_it_is_audited(client, officer_b, b_world):
    _, sub = b_world
    client.force_login(officer_b)
    att = sub.attachments.first()
    r = client.get(reverse("requests:evidence_download", args=[att.pk]))
    assert r.status_code == 200
    assert AuditEvent.objects.filter(action="file_downloaded", actor=officer_b).count() == 1


def test_officer_cannot_see_draft_request_of_own_department(client, officer_a, req_a):
    req_a.status = "DRAFT"
    req_a.save()
    client.force_login(officer_a)
    assert client.get(reverse("my:submit", args=[req_a.pk])).status_code == 403


def test_officer_can_never_verify(officer_b, b_world):
    _, sub = b_world
    with pytest.raises(PermissionDenied):
        wf.verify(sub, officer_b)
    sub.request.refresh_from_db()
    assert sub.request.status == "SUBMITTED"


def test_department_gm_can_submit_for_their_department(gm_a, req_a, pdf_upload):
    sub = wf.submit(
        req_a, gm_a, good_submission(), [validate_upload(pdf_upload(), SUBMISSION_TYPES)]
    )
    assert sub.submitted_by == gm_a


def test_signed_out_user_cannot_download_evidence(client, b_world):
    _, sub = b_world
    r = client.get(reverse("requests:evidence_download", args=[sub.attachments.first().pk]))
    assert r.status_code == 302 and "/accounts/sign-in/" in r["Location"]
