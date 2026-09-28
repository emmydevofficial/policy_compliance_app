"""SPEC 4: the client's procedure, enforced in model and service, not just the interface."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.auditlog.models import AuditEvent
from apps.core.tests.helpers import good_submission
from apps.notifications.models import NotificationOutbox
from apps.workflow import services as wf
from apps.workflow.files import SUBMISSION_TYPES, validate_upload
from apps.workflow.models import ReadOnlyPeriod, Submission

TODAY = timezone.localdate


def files(pdf_upload):
    return [validate_upload(pdf_upload(), SUBMISSION_TYPES)]


def _plan(days):
    return good_submission(
        compliance_status="PARTIALLY_COMPLIANT",
        action_required="File the missing return.",
        action_owner="GM HSE",
        target_resolution_date=TODAY() + timedelta(days=days),
    )


def test_action_plan_within_30_days_is_accepted(req_a, officer_a, pdf_upload):
    sub = wf.submit(req_a, officer_a, _plan(30), files(pdf_upload))
    assert sub.pk


def test_action_plan_beyond_30_days_is_refused(req_a, officer_a, pdf_upload):
    with pytest.raises(ValidationError) as e:
        wf.submit(req_a, officer_a, _plan(31), files(pdf_upload))
    assert "target_resolution_date" in e.value.message_dict
    assert not Submission.objects.exists()


@pytest.mark.parametrize("status", ["PARTIALLY_COMPLIANT", "NON_COMPLIANT"])
def test_partial_or_non_compliance_needs_the_whole_action_plan(
    req_a, officer_a, pdf_upload, status
):
    with pytest.raises(ValidationError) as e:
        wf.submit(req_a, officer_a, good_submission(compliance_status=status), files(pdf_upload))
    assert {"action_required", "action_owner", "target_resolution_date"} <= set(
        e.value.message_dict
    )


def test_action_plan_rule_is_also_enforced_by_the_form(client, officer_a, req_a, pdf_upload):
    client.force_login(officer_a)
    data = {**_plan(45), "files": pdf_upload()}
    r = client.post(reverse("my:submit", args=[req_a.pk]), data)
    assert r.status_code == 200
    assert b"no more than 30 days" in r.content
    assert not Submission.objects.exists()


def test_not_applicable_needs_remarks(req_a, officer_a, pdf_upload):
    with pytest.raises(ValidationError) as e:
        wf.submit(
            req_a, officer_a, good_submission(compliance_status="NOT_APPLICABLE"), files(pdf_upload)
        )
    assert "remarks" in e.value.message_dict


def test_submission_needs_an_attachment_unless_evidence_is_no(req_a, officer_a):
    with pytest.raises(ValidationError):
        wf.submit(req_a, officer_a, good_submission(), [])
    sub = wf.submit(
        req_a,
        officer_a,
        good_submission(
            evidence_available="NO", evidence_description="The audit has not happened yet."
        ),
        [],
    )
    assert sub.attachments.count() == 0


def test_deadline_change_requires_a_reason_and_is_audited(req_a, admin):
    new = req_a.due_date + timedelta(days=7)
    with pytest.raises(ValidationError):
        wf.change_deadline(req_a, new, "  ", admin)
    wf.change_deadline(req_a, new, "NERC extended the window", admin)
    ev = AuditEvent.objects.get(action="deadline_changed")
    assert "NERC extended the window" in ev.detail


def test_verifying_closes_the_request_and_cancels_pending_notices(
    req_a, officer_a, admin, pdf_upload
):
    sub = wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))
    pending = NotificationOutbox.objects.create(
        request=req_a,
        recipient_email="x@example.org",
        template_key="reminder_before",
        kind="REMINDER",
        subject="s",
        body="b",
        scheduled_for=timezone.now(),
        scheduled_date=TODAY() + timedelta(days=1),
    )
    wf.verify(sub, admin)
    req_a.refresh_from_db()
    pending.refresh_from_db()
    assert req_a.status == "VERIFIED" and req_a.closed_at is not None
    assert pending.status == "CANCELLED"


def test_returning_requires_a_comment(req_a, officer_a, admin, pdf_upload):
    sub = wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))
    with pytest.raises(ValidationError):
        wf.return_submission(sub, admin, "")
    wf.return_submission(sub, admin, "Wrong quarter")
    req_a.refresh_from_db()
    assert req_a.status == "RETURNED"


def test_submitting_cancels_pending_reminders(req_a, officer_a, pdf_upload):
    row = NotificationOutbox.objects.create(
        request=req_a,
        recipient_email="x@example.org",
        template_key="reminder_before",
        kind="REMINDER",
        subject="s",
        body="b",
        scheduled_for=timezone.now(),
        scheduled_date=TODAY(),
    )
    wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))
    row.refresh_from_db()
    assert row.status == "CANCELLED"


def test_resubmission_keeps_one_current_submission(req_a, officer_a, admin, pdf_upload):
    first = wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))
    wf.return_submission(first, admin, "Unsigned")
    second = wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))
    first.refresh_from_db()
    assert not first.is_current and second.is_current
    assert req_a.submissions.filter(is_current=True).count() == 1


def test_closed_period_is_read_only_even_for_admin(req_a, officer_a, admin, pdf_upload):
    req_a.period.is_open = False
    req_a.period.save()
    with pytest.raises(ReadOnlyPeriod):
        wf.change_deadline(req_a, req_a.due_date + timedelta(days=1), "reason", admin)
    with pytest.raises(ReadOnlyPeriod):
        wf.close_not_applicable(req_a, "n/a", admin)
    with pytest.raises(ReadOnlyPeriod):
        wf.submit(req_a, officer_a, good_submission(), files(pdf_upload))


def test_reassigning_requires_a_reason(req_a, admin, dept_b, officer_b):
    with pytest.raises(ValidationError):
        wf.reassign(req_a, dept_b, officer_b, "", admin)
    wf.reassign(req_a, dept_b, officer_b, "Finance owns this now", admin)
    req_a.refresh_from_db()
    assert req_a.assigned_department == dept_b
    assert AuditEvent.objects.filter(action="request_reassigned").exists()


def test_closing_not_applicable_needs_justification(req_a, admin):
    with pytest.raises(ValidationError):
        wf.close_not_applicable(req_a, "", admin)
    wf.close_not_applicable(req_a, "No transmission works this quarter", admin)
    req_a.refresh_from_db()
    assert req_a.status == "CLOSED_NA"


def test_one_open_period_only(period):
    from apps.workflow.models import ReportingPeriod

    other = ReportingPeriod(
        name="Q4 2026",
        start_date=period.end_date,
        end_date=period.end_date + timedelta(days=90),
        is_open=True,
    )
    with pytest.raises(ValidationError):
        other.full_clean()


def test_full_cycle_over_http(client, admin, officer_a, gm_a, dept_a, period, pdf_upload):
    """Phase 4 done-when: issue with a PDF, submit with files, return, resubmit, verify."""
    from apps.core.tests.factories import ObligationFactory

    ob = ObligationFactory(primary_department=dept_a)
    client.force_login(admin)
    r = client.post(
        reverse("requests:create"),
        {
            "obligations": [ob.pk],
            "due_date": (TODAY() + timedelta(days=20)).isoformat(),
            "escalate_gm_after_days": 5,
            "issue_now": "1",
            "message": "Please send it.",
            "files": [pdf_upload("circular.pdf")],
        },
    )
    assert r.status_code == 302, r.content
    req = ob.requests.get()
    assert req.status == "AWAITING" and req.attachments.count() == 1
    assert NotificationOutbox.objects.filter(request=req, kind="REQUEST").exists()

    client.force_login(officer_a)
    r = client.post(
        reverse("my:submit", args=[req.pk]),
        {**good_submission(), "files": [pdf_upload("a.pdf"), pdf_upload("b.pdf")]},
    )
    assert r.status_code == 302
    req.refresh_from_db()
    assert req.status == "SUBMITTED"
    sub = req.current_submission
    assert sub.attachments.count() == 2

    client.force_login(admin)
    client.post(
        reverse("requests:verify", args=[sub.pk]),
        {"decision": "return", "comment": "Signature missing"},
    )
    req.refresh_from_db()
    assert req.status == "RETURNED"

    client.force_login(officer_a)
    client.post(
        reverse("my:submit", args=[req.pk]),
        {**good_submission(), "files": pdf_upload("signed.pdf")},
    )
    req.refresh_from_db()
    assert req.status == "SUBMITTED"

    client.force_login(admin)
    client.post(
        reverse("requests:verify", args=[req.current_submission.pk]), {"decision": "verify"}
    )
    req.refresh_from_db()
    assert req.status == "VERIFIED"
    kinds = set(NotificationOutbox.objects.filter(request=req).values_list("kind", flat=True))
    assert {"REQUEST", "RECEIVED", "RETURNED", "VERIFIED"} <= kinds
