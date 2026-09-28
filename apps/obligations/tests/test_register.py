from io import StringIO

import pytest
from django.core.management import call_command
from openpyxl import Workbook

from apps.core.tests.factories import ObligationFactory
from apps.obligations.columns import REGISTER_HEADERS
from apps.obligations.models import Obligation


def test_register_filters_over_htmx_return_only_the_fragment(client, officer_a, req_a, dept_b):
    other = ObligationFactory(
        primary_department=dept_b, description="Metering calibration", risk_level="MEDIUM"
    )
    client.force_login(officer_a)
    r = client.get("/register/?q=calibration", HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    assert b"<html" not in r.content
    assert other.obligation_id.encode() in r.content
    assert req_a.obligation.obligation_id.encode() not in r.content


def test_register_filters_work_without_javascript(client, officer_a, req_a, dept_b):
    ObligationFactory(primary_department=dept_b, risk_level="MEDIUM")
    client.force_login(officer_a)
    r = client.get("/register/?risk=HIGH&status=AWAITING")
    assert b"<html" in r.content
    assert r.content.count(b'class="oid"') == 1


def test_register_is_a_small_number_of_queries(
    client, admin, django_assert_max_num_queries, dept_a, period
):
    for _ in range(30):
        ObligationFactory(primary_department=dept_a)
    client.force_login(admin)
    with django_assert_max_num_queries(12):
        client.get("/register/")


def _workbook(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Obligation Register"])
    ws.append(REGISTER_HEADERS)
    for r in rows:
        ws.append(r)
    path = tmp_path / "register.xlsx"
    wb.save(path)
    return path


def _row(oid, desc="Keep records.", dept="HSE"):
    return [
        oid,
        "TSP Licence",
        "Condition 9",
        "Records",
        desc,
        "Mandatory",
        "Annual",
        dept,
        "Legal; PC&M; All Departments",
        "High",
        "Register; Minutes",
        "Annually",
        "Fines",
    ]


def test_import_dry_run_reports_and_writes_nothing(tmp_path, dept_a):
    existing = ObligationFactory(obligation_id="LIC-900", primary_department=dept_a)
    path = _workbook(tmp_path, [_row("LIC-901")])
    out = StringIO()
    call_command("import_obligations", str(path), "--dry-run", stdout=out)
    text = out.getvalue()
    assert "Created: 1" in text and "LIC-901" in text
    assert "Deactivated: 1" in text and existing.obligation_id in text
    assert not Obligation.objects.filter(obligation_id="LIC-901").exists()
    existing.refresh_from_db()
    assert existing.is_active


def test_import_creates_updates_and_deactivates(tmp_path, dept_a):
    ObligationFactory(obligation_id="LIC-900", primary_department=dept_a, category="Old")
    gone = ObligationFactory(obligation_id="LIC-902", primary_department=dept_a)
    path = _workbook(
        tmp_path, [_row("LIC-900", desc="Submit the annual report to NERC."), _row("LIC-901")]
    )
    call_command("import_obligations", str(path), stdout=StringIO())
    assert Obligation.objects.get(obligation_id="LIC-900").category == "Records"
    assert Obligation.objects.filter(obligation_id="LIC-901", is_active=True).exists()
    gone.refresh_from_db()
    assert not gone.is_active
    ob = Obligation.objects.get(obligation_id="LIC-901")
    names = set(ob.supporting_departments.values_list("name", flat=True))
    assert "Legal" in names and "All Departments" not in names


def test_import_refuses_to_rewrite_text_with_history(tmp_path, req_a):
    oid = req_a.obligation.obligation_id
    path = _workbook(tmp_path, [_row(oid, desc="Entirely new regulatory text.")])
    out = StringIO()
    call_command("import_obligations", str(path), "--keep-missing", stdout=out)
    assert "needs a new obligation ID" in out.getvalue()
    req_a.obligation.refresh_from_db()
    assert req_a.obligation.description != "Entirely new regulatory text."


@pytest.mark.django_db
def test_seed_demo_populates_an_empty_database(settings):
    from apps.accounts.models import User
    from apps.notifications.models import Holiday, NotificationOutbox, NotificationTemplate
    from apps.organisation.models import Department
    from apps.workflow.models import EvidenceRequest, RequestAttachment

    NotificationTemplate.objects.all().delete()
    call_command("seed_demo", "--force-in-production", stdout=StringIO())
    assert Obligation.objects.count() == 82
    assert Department.objects.filter(code="HSE").exists()
    assert Department.objects.count() >= 20
    assert User.objects.filter(role="ADMIN").count() == 1
    assert User.objects.filter(role="EXECUTIVE").count() == 2
    assert User.objects.filter(is_department_gm=True).count() == 20
    assert NotificationTemplate.objects.count() == 10
    assert Holiday.objects.exists()
    statuses = set(EvidenceRequest.objects.values_list("status", flat=True))
    assert {"VERIFIED", "SUBMITTED", "AWAITING", "OVERDUE", "RETURNED", "CLOSED_NA"} <= statuses
    assert NotificationOutbox.objects.filter(request__status="OVERDUE").exists()
    assert RequestAttachment.objects.count() == 2


def test_seed_demo_refuses_without_debug(db):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="DEBUG is False"):
        call_command("seed_demo", stdout=StringIO())
