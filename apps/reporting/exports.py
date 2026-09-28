"""The four exports (SPEC 10). Each returns bytes; the views add headers and the audit event."""

import csv
import io
import tempfile
import zipfile

from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.obligations.columns import REGISTER_HEADERS
from apps.obligations.models import Obligation
from apps.workflow.models import ReportingPeriod, RequestStatus, Submission

from .services import POSITION_LABELS, summarise

HEADER_FILL = PatternFill("solid", fgColor="00849E")
HEADER_FONT = Font(bold=True, color="FFFFFF")

# The client's department tracker sheet. SPEC 10 says "the eighteen columns of their tracker
# sheet" without listing them; these are inferred from the Submission model and must be
# checked against the real workbook before anyone relies on this export.
TRACKER_HEADERS = [
    "Obligation ID",
    "Regulatory Source",
    "Document Reference",
    "Obligation Description",
    "Risk Level",
    "Responsible Department",
    "Evidence / Documentation Required",
    "Deadline",
    "Request Status",
    "Compliance Status",
    "Evidence Available",
    "Evidence Description / Reference",
    "Date of Last Review",
    "Next Review Due",
    "Action Required",
    "Action Owner",
    "Target Resolution Date",
    "Remarks",
]


def _sheet(ws, headers: list[str], rows: list[list], widths: dict[int, int] | None = None):
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(r)
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, 22)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"


def _save(wb: Workbook) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def register_xlsx() -> bytes:
    """Same column order as the client's workbook, exactly."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Obligation Register"
    obs = (
        Obligation.objects.active()
        .select_related("instrument", "primary_department")
        .prefetch_related("supporting_departments")
        .order_by("obligation_id")
    )
    rows = [
        [
            o.obligation_id,
            o.instrument.name,
            o.document_reference,
            o.category,
            o.description,
            o.obligation_type,
            o.frequency,
            o.primary_department.name,
            "; ".join(d.name for d in o.supporting_departments.all()),
            o.get_risk_level_display(),
            o.evidence_required,
            o.regulatory_deadline,
            o.consequence,
        ]
        for o in obs
    ]
    _sheet(ws, REGISTER_HEADERS, rows, {1: 12, 5: 60, 11: 45, 13: 40})
    return _save(wb)


def tracker_xlsx(period: ReportingPeriod | None) -> bytes:
    """One sheet for everything, then one per department."""
    summary = summarise(period)
    wb = Workbook()
    all_ws = wb.active
    all_ws.title = "All departments"

    def line(r):
        s, req = r.sub, r.req
        return [
            r.ob.obligation_id,
            r.ob.instrument.name,
            r.ob.document_reference,
            r.ob.description,
            r.ob.get_risk_level_display(),
            req.assigned_department.name if req else r.ob.primary_department.name,
            req.evidence_required if req else r.ob.evidence_required,
            req.due_date if req else None,
            req.get_status_display() if req else "No request issued",
            POSITION_LABELS.get(r.position, r.position),
            s.get_evidence_available_display() if s else "",
            s.evidence_description if s else "",
            s.date_of_last_review if s else None,
            s.next_review_due if s else None,
            s.action_required if s else "",
            s.action_owner if s else "",
            s.target_resolution_date if s else None,
            s.remarks if s else "",
        ]

    widths = {1: 12, 4: 55, 7: 40, 12: 40, 15: 35, 18: 30}
    _sheet(all_ws, TRACKER_HEADERS, [line(r) for r in summary.rows], widths)
    by_dept: dict[str, list] = {}
    for r in summary.rows:
        name = r.req.assigned_department.name if r.req else r.ob.primary_department.name
        by_dept.setdefault(name, []).append(line(r))
    for name in sorted(by_dept):
        title = "".join(c for c in name if c not in "[]:*?/\\")[:31]
        _sheet(wb.create_sheet(title), TRACKER_HEADERS, by_dept[name], widths)
    for ws in wb.worksheets:
        for col in ("H", "M", "N", "Q"):
            for c in ws[col][1:]:
                c.number_format = "DD MMM YYYY"
    return _save(wb)


def report_html(period: ReportingPeriod | None, *, for_pdf: bool = False) -> str:
    summary = summarise(period)
    evidence = (
        Submission.objects.filter(request__period=summary.period, is_current=True)
        .select_related("request__obligation", "submitted_by")
        .prefetch_related("attachments")
        .order_by("request__obligation__obligation_id")
    )
    return render_to_string(
        "reports/quarterly.html",
        {
            "s": summary,
            "evidence": evidence,
            "for_pdf": for_pdf,
            "generated": timezone.localtime(),
        },
    )


def report_pdf(period: ReportingPeriod | None) -> bytes:
    from weasyprint import HTML

    return HTML(string=report_html(period, for_pdf=True)).write_pdf()


def submission_pack(period: ReportingPeriod):
    """Every verified submission's attachments for the period, in folders named by obligation
    ID, with a manifest. Returns a temporary file positioned at the start."""
    subs = (
        Submission.objects.filter(
            request__period=period, is_current=True, request__status=RequestStatus.VERIFIED
        )
        .select_related("request__obligation", "submitted_by", "verified_by")
        .prefetch_related("attachments")
        .order_by("request__obligation__obligation_id")
    )
    tmp = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(
        [
            "filename",
            "obligation",
            "submitted_by",
            "submitted_at",
            "verified_by",
            "verified_at",
            "sha256",
            "size_bytes",
        ]
    )
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in subs:
            oid = sub.request.obligation.obligation_id
            used: set[str] = set()
            for att in sub.attachments.all():
                name = att.original_filename
                stem, dot, ext = name.rpartition(".")
                n = 2
                while name in used:
                    name = f"{stem} ({n}).{ext}" if dot else f"{att.original_filename} ({n})"
                    n += 1
                used.add(name)
                arc = f"{oid}/{name}"
                with att.file.open("rb") as fh:
                    zf.writestr(arc, fh.read())
                writer.writerow(
                    [
                        arc,
                        oid,
                        sub.submitted_by.email,
                        timezone.localtime(sub.submitted_at).isoformat(timespec="minutes"),
                        sub.verified_by.email if sub.verified_by else "",
                        timezone.localtime(sub.verified_at).isoformat(timespec="minutes")
                        if sub.verified_at
                        else "",
                        att.sha256,
                        att.size_bytes,
                    ]
                )
        zf.writestr("manifest.csv", manifest.getvalue())
    tmp.seek(0)
    return tmp
