from django.db.models import OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from apps.auditlog.models import AuditEvent
from apps.core.htmx import is_htmx
from apps.core.permissions import any_role_required
from apps.organisation.models import Department
from apps.workflow.models import EvidenceRequest, ReportingPeriod, RequestStatus, Submission

from .models import Obligation, RegulatoryInstrument, RiskLevel

NO_REQUEST = "NONE"


def register_queryset(params, period: ReportingPeriod | None):
    current = EvidenceRequest.objects.filter(obligation=OuterRef("pk"), period=period)
    qs = (
        Obligation.objects.active()
        .select_related("instrument", "primary_department")
        .annotate(
            current_status=Coalesce(Subquery(current.values("status")[:1]), Value(NO_REQUEST))
        )
        .prefetch_related(
            Prefetch(
                "requests",
                queryset=EvidenceRequest.objects.filter(period=period).select_related(
                    "assigned_department"
                ),
                to_attr="period_requests",
            )
        )
    )
    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(obligation_id__icontains=q)
            | Q(description__icontains=q)
            | Q(category__icontains=q)
            | Q(document_reference__icontains=q)
        )
    if params.get("instrument", "").isdigit():
        qs = qs.filter(instrument_id=int(params["instrument"]))
    if params.get("department", "").isdigit():
        qs = qs.filter(primary_department_id=int(params["department"]))
    if params.get("risk") in RiskLevel.values:
        qs = qs.filter(risk_level=params["risk"])
    status = params.get("status", "")
    if status in RequestStatus.values or status == NO_REQUEST:
        qs = qs.filter(current_status=status)
    return qs.order_by("obligation_id")


@any_role_required
def register(request):
    period = ReportingPeriod.current()
    obligations = register_queryset(request.GET, period)
    ctx = {
        "obligations": obligations,
        "period": period,
        "params": request.GET,
        "instruments": RegulatoryInstrument.objects.filter(is_active=True),
        "departments": Department.objects.active(),
        "risks": RiskLevel.choices,
        "statuses": [*RequestStatus.choices, (NO_REQUEST, "No request this period")],
    }
    if is_htmx(request):
        return render(request, "components/register_rows.html", ctx)
    return render(request, "obligations/register.html", ctx)


@any_role_required
def detail(request, obligation_id: str):
    ob = get_object_or_404(
        Obligation.objects.select_related("instrument", "primary_department").prefetch_related(
            "supporting_departments"
        ),
        obligation_id=obligation_id,
    )
    user = request.user
    reqs = (
        EvidenceRequest.objects.visible_to(user)
        .filter(obligation=ob)
        .with_related()
        .prefetch_related(
            "attachments",
            Prefetch(
                "submissions",
                queryset=Submission.objects.select_related(
                    "submitted_by", "verified_by"
                ).prefetch_related("attachments"),
            ),
        )
        .order_by("-period__start_date")
    )
    period = ReportingPeriod.current()
    current = next((r for r in reqs if period and r.period_id == period.pk), None)
    trail = AuditEvent.objects.filter(obligation_ref=ob.obligation_id).select_related("actor")
    if user.role == "OFFICER" and not any(
        r.assigned_department_id == user.department_id for r in reqs
    ):
        trail = trail.filter(action__startswith="obligation_")
    return render(
        request,
        "obligations/detail.html",
        {
            "ob": ob,
            "current": current,
            "history": [r for r in reqs if r is not current],
            "trail": trail[:100],
            "period": period,
        },
    )
