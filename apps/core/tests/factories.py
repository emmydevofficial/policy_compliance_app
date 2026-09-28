import factory
from django.utils import timezone

from apps.accounts.models import NotificationPreference, Role, User
from apps.notifications.defaults import DEFAULT_TEMPLATES
from apps.notifications.models import NotificationTemplate
from apps.obligations.models import Obligation, RegulatoryInstrument
from apps.organisation.models import Department
from apps.workflow.models import EvidenceRequest, ReportingPeriod

PASSWORD = "correct-horse-battery-9"


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

    name = factory.Sequence(lambda n: f"Department {n}")
    code = factory.Sequence(lambda n: f"D{n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.org")
    full_name = factory.Sequence(lambda n: f"Person {n}")
    role = Role.OFFICER
    department = factory.SubFactory(DepartmentFactory)

    @factory.post_generation
    def password(obj, create, extracted, **kw):
        obj.set_password(extracted or PASSWORD)
        if create:
            obj.save()
            NotificationPreference.objects.get_or_create(user=obj)


class AdminFactory(UserFactory):
    role = Role.ADMIN
    department = None


class ExecutiveFactory(UserFactory):
    role = Role.EXECUTIVE
    department = None


class InstrumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegulatoryInstrument
        django_get_or_create = ("short_code",)

    name = "TSP Licence"
    short_code = "LIC"


class ObligationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Obligation

    obligation_id = factory.Sequence(lambda n: f"LIC-{n + 100:03d}")
    instrument = factory.SubFactory(InstrumentFactory)
    document_reference = "Condition 2.1"
    category = "Reporting – NERC"
    description = "Submit the annual report to NERC."
    frequency = "Annual"
    primary_department = factory.SubFactory(DepartmentFactory)
    risk_level = "HIGH"
    evidence_required = "Annual report; NERC acknowledgement"
    regulatory_deadline = "Within 30 days of year end"
    consequence = "Licence sanctions"


class PeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReportingPeriod
        django_get_or_create = ("name",)

    name = "Q3 2026"
    start_date = factory.LazyFunction(lambda: timezone.localdate().replace(month=7, day=1))
    end_date = factory.LazyFunction(lambda: timezone.localdate().replace(month=9, day=30))
    is_open = True


class RequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EvidenceRequest

    obligation = factory.SubFactory(ObligationFactory)
    period = factory.SubFactory(PeriodFactory)
    assigned_department = factory.LazyAttribute(lambda o: o.obligation.primary_department)
    due_date = factory.LazyFunction(lambda: timezone.localdate() + timezone.timedelta(days=14))
    evidence_required = factory.LazyAttribute(lambda o: o.obligation.evidence_required)
    status = "AWAITING"


def seed_templates():
    for key, (name, subject, body) in DEFAULT_TEMPLATES.items():
        NotificationTemplate.objects.get_or_create(
            key=key, defaults={"name": name, "subject_template": subject, "body_template": body}
        )
