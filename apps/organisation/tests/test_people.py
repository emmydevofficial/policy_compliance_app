import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.auditlog.models import AuditEvent
from apps.organisation import services
from apps.organisation.models import Department


def test_department_with_open_requests_cannot_be_deactivated(req_a, admin, dept_a):
    with pytest.raises(ValidationError) as e:
        services.deactivate_department(dept_a, admin)
    assert req_a.obligation.obligation_id in str(e.value)
    dept_a.refresh_from_db()
    assert dept_a.is_active


def test_department_deactivation_is_soft_and_audited(admin):
    d = Department.objects.create(name="Old", code="OLD")
    services.deactivate_department(d, admin)
    assert Department.objects.filter(pk=d.pk, is_active=False).exists()
    assert AuditEvent.objects.filter(action="department_deactivated").exists()


def test_person_with_open_requests_must_be_reassigned_first(req_a, admin, officer_a, dept_a):
    from apps.core.tests.factories import UserFactory

    with pytest.raises(ValidationError):
        services.deactivate_person(officer_a, admin)
    other = UserFactory(email="other@example.org", department=dept_a)
    services.deactivate_person(officer_a, admin, reassign_to={req_a.pk: other})
    req_a.refresh_from_db()
    officer_a.refresh_from_db()
    assert req_a.assigned_officer == other and not officer_a.is_active


def test_deactivate_page_lists_open_requests(client, admin, officer_a, req_a):
    client.force_login(admin)
    r = client.get(f"/manage/people/{officer_a.pk}/deactivate/")
    assert req_a.obligation.obligation_id.encode() in r.content


def test_role_change_is_audited(admin, officer_a):
    officer_a.role = "EXECUTIVE"
    officer_a.department = None
    officer_a.is_department_gm = False
    services.update_person(officer_a, admin, old_role="OFFICER", old_department_id=None)
    assert AuditEvent.objects.filter(action="role_changed").exists()


CSV = """full_name,email,job_title,phone,role,department_code,is_department_gm
Ngozi Eze,ngozi@example.org,Officer,,OFFICER,HSE,no
Ada Officer,officer.a@example.org,Senior Officer,,OFFICER,HSE,no
"""


def test_people_csv_dry_run_writes_nothing(admin, officer_a):
    before = User.objects.count()
    report = services.import_people(CSV, admin, dry_run=True)
    assert report.ok and len(report.create) == 1 and len(report.update) == 1
    assert User.objects.count() == before
    officer_a.refresh_from_db()
    assert officer_a.job_title == ""


def test_people_csv_live_run(admin, officer_a):
    report = services.import_people(CSV, admin, dry_run=False)
    assert report.ok
    ngozi = User.objects.get(email="ngozi@example.org")
    assert not ngozi.has_usable_password()
    officer_a.refresh_from_db()
    assert officer_a.job_title == "Senior Officer"


def test_people_csv_with_errors_writes_nothing(admin, dept_a):
    bad = CSV + "Bad Row,bad@example.org,,,WIZARD,HSE,no\n"
    report = services.import_people(bad, admin, dry_run=False)
    assert not report.ok
    assert not User.objects.filter(email="ngozi@example.org").exists()


def test_import_screen_dry_run_then_confirm(client, admin, dept_a):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(admin)
    f = SimpleUploadedFile("people.csv", CSV.encode(), content_type="text/csv")
    r = client.post("/manage/people/import/", {"file": f})
    assert b"Dry run" in r.content
    assert not User.objects.filter(email="ngozi@example.org").exists()
    r = client.post("/manage/people/import/", {"confirm": "1"})
    assert r.status_code == 302
    assert User.objects.filter(email="ngozi@example.org").exists()
