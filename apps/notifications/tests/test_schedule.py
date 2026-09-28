"""SPEC 8 and 14: the reminder schedule, the daily command, escalations and delivery."""

from datetime import date, timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from freezegun import freeze_time

from apps.auditlog.models import AuditEvent
from apps.core.tests.factories import ObligationFactory, RequestFactory
from apps.notifications import services as notices
from apps.notifications.models import Holiday, NotificationOutbox, ReminderRule

AS_OF = date(2026, 10, 7)  # a Wednesday


@pytest.fixture
def make_request(dept_a, officer_a, gm_a, period):
    def make(days: int, status="AWAITING", risk="HIGH"):
        ob = ObligationFactory(primary_department=dept_a, risk_level=risk)
        return RequestFactory(
            obligation=ob,
            period=period,
            assigned_department=dept_a,
            assigned_officer=officer_a,
            due_date=AS_OF + timedelta(days=days),
            status=status,
        )

    return make


def due_kind(req, day=AS_OF):
    return notices.deadline_notice_due(req, day, ReminderRule.get(), notices.holiday_set())


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (14, "REMINDER"),
        (7, "REMINDER"),
        (3, "REMINDER"),
        (1, "REMINDER"),
        (0, "FINAL"),
        (10, None),
        (2, None),
    ],
)
def test_notice_for_request_due_in(make_request, days, expected):
    assert due_kind(make_request(days)) == expected


def test_overdue_by_six_days_follows_working_days(make_request):
    # Due Thursday 1 Oct. Working days after it: Fri 2, Mon 5, Tue 6, Wed 7 -> the 4th,
    # a multiple of the 2-day repeat: an overdue notice is due today.
    req = make_request(-6, status="OVERDUE")
    assert due_kind(req) == "OVERDUE"


def test_public_holiday_in_the_window_moves_the_overdue_series(make_request):
    Holiday.objects.create(date=date(2026, 10, 5), name="Monday holiday")
    req = make_request(-6, status="OVERDUE")
    # Now Fri 2, Tue 6, Wed 7: the 3rd working day; the notice went on Tue 6 instead.
    assert due_kind(req) is None
    assert due_kind(req, date(2026, 10, 6)) == "OVERDUE"


def test_reminder_that_falls_on_a_holiday_comes_the_working_day_before(make_request):
    Holiday.objects.create(date=date(2026, 10, 8), name="Thursday holiday")
    req = make_request(8)  # due Thu 15 Oct; 7 days before is the holiday on Thu 8 Oct
    assert due_kind(req) == "REMINDER"
    assert due_kind(req, date(2026, 10, 8)) is None


def test_deadline_on_a_weekend_gets_final_notice_on_friday(make_request):
    req = make_request(3)  # Saturday 10 Oct
    assert due_kind(req, date(2026, 10, 9)) == "FINAL"


def test_nothing_is_sent_on_a_weekend(make_request):
    req = make_request(7)
    assert due_kind(req, date(2026, 10, 10)) is None


def test_stop_after_count(make_request):
    rule = ReminderRule.get()
    rule.stop_after_count = 1
    rule.save()
    req = make_request(-6, status="OVERDUE")
    assert due_kind(req) is None  # the single allowed notice went on Mon 5 Oct


def test_returned_request_restarts_the_overdue_series_from_the_return_date(
    make_request, officer_a, admin, pdf_upload
):
    from apps.core.tests.helpers import good_submission
    from apps.workflow import services as wf
    from apps.workflow.files import SUBMISSION_TYPES, validate_upload

    req = make_request(-10)
    with freeze_time("2026-10-05 10:00"):
        sub = wf.submit(
            req, officer_a, good_submission(), [validate_upload(pdf_upload(), SUBMISSION_TYPES)]
        )
        wf.return_submission(sub, admin, "Unsigned")
    req.refresh_from_db()
    req.status = "OVERDUE"
    # Anchored on Mon 5 Oct: the first notice is two working days later, Wed 7 Oct.
    assert due_kind(req, date(2026, 10, 6)) is None
    assert due_kind(req, date(2026, 10, 7)) == "OVERDUE"


def run(as_of=AS_OF, dry=False):
    out = StringIO()
    args = ["run_daily_notices", "--as-of", as_of.isoformat()]
    if dry:
        args.append("--dry-run")
    with freeze_time(f"{as_of.isoformat()} 06:55"):  # 07:55 Lagos
        call_command(*args, stdout=out)
    return out.getvalue()


def test_daily_command_is_idempotent(make_request):
    for days in (14, 7, 3, 1, 0):
        make_request(days)
    make_request(-6)
    run()
    first = NotificationOutbox.objects.count()
    assert first >= 6
    run()
    assert NotificationOutbox.objects.count() == first


def test_daily_command_marks_overdue_and_audits(make_request):
    req = make_request(-1)
    run()
    req.refresh_from_db()
    assert req.status == "OVERDUE"
    assert AuditEvent.objects.filter(action="request_overdue", actor__isnull=True).exists()


def test_dry_run_writes_nothing_and_sends_nothing(make_request):
    req = make_request(-6)
    make_request(7)
    audit_before = AuditEvent.objects.count()
    output = run(dry=True)
    req.refresh_from_db()
    assert req.status == "AWAITING"
    assert NotificationOutbox.objects.count() == 0
    assert AuditEvent.objects.count() == audit_before
    assert len(mail.outbox) == 0
    assert "DRY RUN" in output and "OVERDUE" in output and "REMINDER" in output


def test_dry_run_matches_the_live_run(make_request):
    for days in (14, 3, 0, -6):
        make_request(days)
    dry = run(dry=True)
    live = run()
    strip = lambda s: [ln for ln in s.splitlines()[1:] if "DRY RUN" not in ln]  # noqa: E731
    assert [ln.replace("Would send", "Sent") for ln in strip(dry)] == strip(live)


def test_live_run_sends_and_marks_sent(make_request, officer_a, gm_a):
    make_request(7)
    run()
    row = NotificationOutbox.objects.get(kind="REMINDER")
    assert row.status == "SENT" and row.sent_at
    assert mail.outbox[-1].to == [officer_a.email]
    assert gm_a.email in mail.outbox[-1].cc
    assert mail.outbox[-1].alternatives  # HTML part
    row.request.refresh_from_db()
    assert row.request.reminders_sent == 1


def test_gm_escalation_is_sent_once(make_request, gm_a):
    req = make_request(-10, status="OVERDUE")  # 27 Sep; 5 working days later is 2 Oct
    run()
    run(AS_OF + timedelta(days=1))
    esc = NotificationOutbox.objects.filter(kind="ESCALATION_GM")
    assert esc.count() == 1 and esc.get().recipient_email == gm_a.email
    req.refresh_from_db()
    assert req.escalated_to_gm_at is not None


def test_management_escalation_only_for_high_risk(make_request, executive):
    high = make_request(-30, status="OVERDUE", risk="HIGH")
    medium = make_request(-30, status="OVERDUE", risk="MEDIUM")
    run()
    esc = NotificationOutbox.objects.filter(kind="ESCALATION_MGMT")
    assert list(esc.values_list("request_id", flat=True)) == [high.pk]
    medium.refresh_from_db()
    assert medium.escalated_to_management_at is None


def test_failed_delivery_retries_then_fails_and_is_reported_monday(make_request, admin):
    make_request(7)
    with mock.patch(
        "django.core.mail.EmailMultiAlternatives.send", side_effect=ConnectionError("SMTP down")
    ):
        for i in range(5):
            run(AS_OF + timedelta(days=i) if i < 3 else AS_OF + timedelta(days=i + 2))
    row = NotificationOutbox.objects.get(kind="REMINDER", scheduled_date=AS_OF)
    assert row.attempts == 5 and row.status == "FAILED"
    assert "SMTP down" in row.last_error
    monday = date(2026, 10, 19)
    run(monday)
    digest = NotificationOutbox.objects.get(
        kind="DIGEST", recipient_email=admin.email, scheduled_date=monday
    )
    assert "failed after five attempts" in digest.body


def test_medium_risk_reminders_respect_opt_out_but_high_risk_do_not(make_request, officer_a):
    prefs = officer_a.notification_prefs
    prefs.deadline_reminders = False
    prefs.high_risk_deadline_reminders = False  # save() forces it back on
    prefs.save()
    prefs.refresh_from_db()
    assert prefs.high_risk_deadline_reminders is True
    high = make_request(7, risk="HIGH")
    medium = make_request(7, risk="MEDIUM")
    assert notices.addressees(high, "REMINDER").to == officer_a
    assert officer_a not in [
        notices.addressees(medium, "REMINDER").to,
        *notices.addressees(medium, "REMINDER").cc,
    ]


def test_delegate_is_copied_during_leave(make_request, officer_a, dept_a):
    from apps.core.tests.factories import UserFactory

    cover = UserFactory(email="cover@example.org", department=dept_a)
    officer_a.delegate_to = cover
    officer_a.delegate_from = AS_OF - timedelta(days=1)
    officer_a.delegate_until = AS_OF + timedelta(days=5)
    officer_a.save()
    to = notices.addressees(make_request(7), "REMINDER", on=AS_OF)
    assert cover in to.cc


def test_event_notice_is_sent_when_the_request_is_issued(
    dept_a, officer_a, admin, period, django_capture_on_commit_callbacks
):
    from apps.workflow import services as wf

    ob = ObligationFactory(primary_department=dept_a)
    with django_capture_on_commit_callbacks(execute=True):
        wf.create_requests(
            obligations=[ob],
            period=period,
            actor=admin,
            due_date=AS_OF + timedelta(days=30),
            officer=officer_a,
        )
    row = NotificationOutbox.objects.get(kind="REQUEST")
    assert row.status == "SENT"
    assert ob.obligation_id in mail.outbox[-1].subject
