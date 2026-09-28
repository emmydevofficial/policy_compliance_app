from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header

from apps.auditlog.services import Action, record
from apps.core.permissions import admin_required, executive_or_above
from apps.workflow.models import ReportingPeriod

from . import exports
from .services import summarise

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period(request) -> ReportingPeriod | None:
    pid = request.GET.get("period", "")
    if pid.isdigit():
        return ReportingPeriod.objects.filter(pk=int(pid)).first()
    return ReportingPeriod.current()


def _download(data, filename: str, content_type: str, request, what: str):
    record(
        Action.EXPORT_GENERATED,
        actor=request.user,
        object_type="Export",
        object_id=filename,
        request=request,
        detail=f"{what} exported as {filename}.",
    )
    if isinstance(data, bytes):
        response = HttpResponse(data, content_type=content_type)
    else:
        response = FileResponse(data, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(True, filename)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _stamp() -> str:
    return timezone.localtime().strftime("%Y%m%d-%H%M")


@admin_required
def admin_dashboard(request):
    return render(
        request,
        "dashboard/admin.html",
        {"s": summarise(_period(request)), "periods": ReportingPeriod.objects.all()},
    )


@executive_or_above
def executive_dashboard(request):
    return render(
        request,
        "dashboard/executive.html",
        {"s": summarise(_period(request)), "periods": ReportingPeriod.objects.all()},
    )


@executive_or_above
def index(request):
    return render(
        request,
        "reports/index.html",
        {"period": _period(request), "periods": ReportingPeriod.objects.all()},
    )


@executive_or_above
def preview(request):
    return render(
        request,
        "reports/preview.html",
        {"report": exports.report_html(_period(request)), "period": _period(request)},
    )


@executive_or_above
def register_xlsx(request):
    return _download(
        exports.register_xlsx(),
        f"obligation-register-{_stamp()}.xlsx",
        XLSX,
        request,
        "Obligation register",
    )


@executive_or_above
def tracker_xlsx(request):
    p = _period(request)
    return _download(
        exports.tracker_xlsx(p),
        f"department-tracker-{p.name if p else 'none'}-{_stamp()}.xlsx".replace(" ", "-"),
        XLSX,
        request,
        "Department tracker",
    )


@executive_or_above
def report_pdf(request):
    p = _period(request)
    return _download(
        exports.report_pdf(p),
        f"compliance-status-report-{p.name if p else 'none'}.pdf".replace(" ", "-"),
        "application/pdf",
        request,
        "Quarterly compliance status report",
    )


@executive_or_above
def submission_pack(request):
    p = _period(request)
    if p is None:
        return HttpResponse("No reporting period.", status=404)
    return _download(
        exports.submission_pack(p),
        f"submission-pack-{p.name}.zip".replace(" ", "-"),
        "application/zip",
        request,
        f"Submission pack for {p.name}",
    )
