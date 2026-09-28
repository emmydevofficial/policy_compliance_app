import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.pdfgen import simple_pdf
from apps.core.tests.factories import (
    AdminFactory,
    DepartmentFactory,
    ExecutiveFactory,
    ObligationFactory,
    PeriodFactory,
    RequestFactory,
    UserFactory,
    seed_templates,
)


@pytest.fixture(autouse=True)
def _templates(db):
    seed_templates()


@pytest.fixture
def dept_a(db):
    return DepartmentFactory(name="HSE", code="HSE")


@pytest.fixture
def dept_b(db):
    return DepartmentFactory(name="Finance & Accounts", code="FIN")


@pytest.fixture
def admin(db):
    return AdminFactory(email="admin@example.org", full_name="Grace Admin")


@pytest.fixture
def officer_a(dept_a):
    return UserFactory(email="officer.a@example.org", department=dept_a, full_name="Ada Officer")


@pytest.fixture
def gm_a(dept_a):
    gm = UserFactory(
        email="gm.a@example.org", department=dept_a, is_department_gm=True, full_name="Gbenga GM"
    )
    dept_a.gm = gm
    dept_a.save()
    return gm


@pytest.fixture
def officer_b(dept_b):
    return UserFactory(email="officer.b@example.org", department=dept_b, full_name="Bola Officer")


@pytest.fixture
def executive(db):
    return ExecutiveFactory(email="exec@example.org", full_name="Efe Executive")


@pytest.fixture
def period(db):
    return PeriodFactory()


@pytest.fixture
def req_a(dept_a, officer_a, gm_a, period):
    ob = ObligationFactory(primary_department=dept_a)
    return RequestFactory(
        obligation=ob, period=period, assigned_department=dept_a, assigned_officer=officer_a
    )


@pytest.fixture
def req_b(dept_b, officer_b, period):
    ob = ObligationFactory(primary_department=dept_b)
    return RequestFactory(
        obligation=ob, period=period, assigned_department=dept_b, assigned_officer=officer_b
    )


@pytest.fixture
def pdf_upload():
    def make(name="evidence.pdf"):
        return SimpleUploadedFile(name, simple_pdf(["Evidence"]), content_type="application/pdf")

    return make
