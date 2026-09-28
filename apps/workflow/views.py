from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.auditlog.services import Action, record
from apps.core.permissions import admin_required, any_role_required, officer_required
from apps.notifications.models import NotificationTemplate
from apps.notifications.rendering import render_notice
from apps.notifications.services import request_context, schedule_preview
from apps.obligations.models import Obligation

from . import services
from .files import file_response
from .forms import (
    CloseNAForm,
    DeadlineForm,
    ObligationPickerForm,
    ReassignForm,
    RequestAttachmentForm,
    RequestCreateForm,
    SubmissionForm,
    VerificationForm,
)
from .models import (
    AWAITING_OFFICER,
    EvidenceRequest,
    InvalidTransition,
    ReadOnlyPeriod,
    ReportingPeriod,
    RequestAttachment,
    RequestStatus,
    Submission,
    SubmissionAttachment,
)

S = RequestStatus


def _flash_errors(request, exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        msgs = (
            [m for ms in exc.message_dict.values() for m in ms]
            if hasattr(exc, "message_dict")
            else exc.messages
        )
    else:
        msgs = [str(exc)]
    for m in msgs:
        messages.error(request, m)


def _period_from(request) -> ReportingPeriod | None:
    pid = request.GET.get("period", "")
    if pid.isdigit():
        return ReportingPeriod.objects.filter(pk=int(pid)).first()
    return ReportingPeriod.current()


def _submissions_prefetch():
    return Prefetch(
        "submissions",
        queryset=Submission.objects.select_related("submitted_by", "verified_by").prefetch_related(
            "attachments"
        ),
    )


# --- admin: lists -----------------------------------------------------------------------
@admin_required
def request_list(request):
    period = _period_from(request)
    qs = EvidenceRequest.objects.with_related().filter(period=period)
    dept = request.GET.get("department", "")
    if dept.isdigit():
        qs = qs.filter(assigned_department_id=int(dept))
    groups = []
    for value, label in S.choices:
        items = [r for r in qs if r.status == value]
        groups.append(
            {
                "status": value,
                "label": label,
                "items": items,
                "css": items[0].status_css if items else "na",
            }
        )
    from apps.organisation.models import Department

    return render(
        request,
        "requests/list.html",
        {
            "groups": groups,
            "period": period,
            "periods": ReportingPeriod.objects.all(),
            "total": sum(len(g["items"]) for g in groups),
            "departments": Department.objects.active(),
            "department": dept,
        },
    )


def _available_obligations(period):
    taken = EvidenceRequest.objects.filter(period=period).values("obligation_id")
    return (
        Obligation.objects.active()
        .exclude(pk__in=taken)
        .select_related("instrument", "primary_department")
    )


@admin_required
def request_create(request):
    period = ReportingPeriod.current()
    if period is None:
        messages.error(request, "There is no open reporting period. Open one first.")
        return redirect("admin_area:periods")
    available = _available_obligations(period)
    picker = ObligationPickerForm(request.GET or None)
    preselected = set(picker.matches(available).values_list("pk", flat=True))
    one = request.GET.get("obligation", "")
    if one.isdigit():
        preselected.add(int(one))
    form = RequestCreateForm(
        request.POST or None,
        request.FILES or None,
        available=available,
        initial={"obligations": list(preselected)},
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            result = services.create_requests(
                obligations=list(d["obligations"]),
                period=period,
                actor=request.user,
                due_date=d["due_date"],
                department=d["department"],
                officer=d["officer"],
                evidence_required=d["evidence_required"],
                message=d["message"],
                escalate_gm_after_days=d["escalate_gm_after_days"],
                files=d["files"],
                issue_now=d["issue_now"],
                http_request=request,
            )
        except (ValidationError, ReadOnlyPeriod) as exc:
            _flash_errors(request, exc)
        else:
            verb = "issued" if d["issue_now"] else "saved as draft"
            messages.success(request, f"{len(result.created)} request(s) {verb}.")
            for s in result.skipped:
                messages.warning(request, s)
            if len(result.created) == 1:
                return redirect("requests:detail", pk=result.created[0].pk)
            return redirect("requests:list")
    return render(
        request,
        "requests/create.html",
        {
            "form": form,
            "picker": picker,
            "period": period,
            "available": available,
            "selected": {int(v) for v in (form["obligations"].value() or [])},
        },
    )


@admin_required
def request_picker(request):
    """HTMX: the obligation checklist, pre-ticked by department, instrument or risk."""
    period = ReportingPeriod.current()
    available = _available_obligations(period)
    picker = ObligationPickerForm(request.GET)
    selected = set(picker.matches(available).values_list("pk", flat=True))
    selected |= {int(v) for v in request.GET.getlist("obligations") if v.isdigit()}
    return render(
        request,
        "components/obligation_checklist.html",
        {"available": available, "selected": selected},
    )


@admin_required
@require_POST
def request_preview(request):
    """HTMX: the email the first chosen obligation's officer would receive, and the schedule."""
    period = ReportingPeriod.current()
    ids = [int(v) for v in request.POST.getlist("obligations") if v.isdigit()]
    ob = (
        Obligation.objects.select_related("instrument", "primary_department")
        .filter(pk__in=ids)
        .order_by("obligation_id")
        .first()
    )
    template = NotificationTemplate.objects.filter(key="evidence_request").first()
    ctx = {"count": len(ids)}
    if ob and template and period:
        from apps.organisation.models import Department

        dept = ob.primary_department
        dept_id = request.POST.get("department", "")
        if dept_id.isdigit():
            dept = Department.objects.filter(pk=int(dept_id)).first() or dept
        officer = None
        off_id = request.POST.get("officer", "")
        if off_id.isdigit():
            officer = User.objects.filter(pk=int(off_id)).first()
        due = timezone.localdate()
        try:
            from datetime import date

            due = date.fromisoformat(request.POST.get("due_date", ""))
        except ValueError:
            pass
        esc = request.POST.get("escalate_gm_after_days", "5")
        probe = EvidenceRequest(
            obligation=ob,
            period=period,
            assigned_department=dept,
            assigned_officer=officer,
            due_date=due,
            message=request.POST.get("message", ""),
            evidence_required=request.POST.get("evidence_required", "").strip()
            or ob.evidence_required,
            escalate_gm_after_days=int(esc) if esc.isdigit() else 5,
        )
        subject, body, _ = render_notice(template, request_context(probe, link="(upload link)"))
        if probe.message:
            body = probe.message + "\n\n" + body
        ctx.update(subject=subject, body=body, ob=ob, schedule=schedule_preview(probe))
    return render(request, "components/email_preview.html", ctx)


@admin_required
def request_detail(request, pk: int):
    req = get_object_or_404(
        EvidenceRequest.objects.with_related().prefetch_related(
            "attachments", _submissions_prefetch()
        ),
        pk=pk,
    )
    current = req.current_submission
    return render(
        request,
        "requests/detail.html",
        {
            "req": req,
            "current": current,
            "submissions": list(req.submissions.all()),
            "outbox": req.outbox.order_by("-scheduled_for")[:50],
            "schedule": schedule_preview(req) if req.awaiting_officer else [],
            "deadline_form": DeadlineForm(initial={"due_date": req.due_date}),
            "reassign_form": ReassignForm(
                initial={"department": req.assigned_department, "officer": req.assigned_officer}
            ),
            "close_form": CloseNAForm(),
            "attach_form": RequestAttachmentForm(),
            "verify_form": VerificationForm(),
        },
    )


def _act(request, pk: int, action):
    req = get_object_or_404(EvidenceRequest.objects.with_related(), pk=pk)
    try:
        msg = action(req)
    except (ValidationError, InvalidTransition, ReadOnlyPeriod) as exc:
        _flash_errors(request, exc)
    else:
        if msg:
            messages.success(request, msg)
    return redirect("requests:detail", pk=pk)


@admin_required
@require_POST
def request_issue(request, pk: int):
    def go(r):
        services.issue_request(r, request.user, http_request=request)
        return "Request issued and the department notified."

    return _act(request, pk, go)


@admin_required
@require_POST
def request_deadline(request, pk: int):
    form = DeadlineForm(request.POST)

    def go(r):
        if not form.is_valid():
            raise ValidationError([e for es in form.errors.values() for e in es])
        services.change_deadline(
            r,
            form.cleaned_data["due_date"],
            form.cleaned_data["reason"],
            request.user,
            http_request=request,
        )
        return f"Deadline changed to {form.cleaned_data['due_date']:%d %b %Y}."

    return _act(request, pk, go)


@admin_required
@require_POST
def request_reassign(request, pk: int):
    form = ReassignForm(request.POST)

    def go(r):
        if not form.is_valid():
            raise ValidationError([e for es in form.errors.values() for e in es])
        d = form.cleaned_data
        services.reassign(
            r, d["department"], d["officer"], d["reason"], request.user, http_request=request
        )
        return f"Reassigned to {d['department'].name}."

    return _act(request, pk, go)


@admin_required
@require_POST
def request_close_na(request, pk: int):
    form = CloseNAForm(request.POST)

    def go(r):
        if not form.is_valid():
            raise ValidationError("A written justification is required.")
        services.close_not_applicable(
            r, form.cleaned_data["justification"], request.user, http_request=request
        )
        return "Closed as not applicable."

    return _act(request, pk, go)


@admin_required
@require_POST
def request_attach(request, pk: int):
    form = RequestAttachmentForm(request.POST, request.FILES)

    def go(r):
        if not form.is_valid():
            if form.errors:
                record(
                    Action.FILE_REJECTED,
                    obj=r,
                    request=request,
                    detail="; ".join(e for es in form.errors.values() for e in es)[:1000],
                )
            raise ValidationError([e for es in form.errors.values() for e in es])
        for f in form.cleaned_data["files"]:
            services.add_request_attachment(
                r,
                None,
                request.user,
                clean=f,
                description=form.cleaned_data["description"],
                http_request=request,
            )
        return f"{len(form.cleaned_data['files'])} document(s) attached."

    return _act(request, pk, go)


# --- admin: verification ----------------------------------------------------------------
@admin_required
def verify_queue(request):
    reqs = (
        EvidenceRequest.objects.with_related()
        .filter(status=S.SUBMITTED)
        .prefetch_related("attachments", _submissions_prefetch())
        .order_by("updated_at")
    )
    return render(
        request,
        "requests/verify_queue.html",
        {"items": [(r, r.current_submission) for r in reqs], "form": VerificationForm()},
    )


@admin_required
@require_POST
def verify_submission(request, pk: int):
    sub = get_object_or_404(
        Submission.objects.select_related("request", "request__period", "request__obligation"),
        pk=pk,
    )
    form = VerificationForm(request.POST)
    if not form.is_valid():
        for es in form.errors.values():
            for e in es:
                messages.error(request, e)
    else:
        try:
            if form.cleaned_data["decision"] == "verify":
                services.verify(
                    sub, request.user, form.cleaned_data["comment"], http_request=request
                )
                messages.success(request, f"{sub.request.obligation.obligation_id} verified.")
            else:
                services.return_submission(
                    sub, request.user, form.cleaned_data["comment"], http_request=request
                )
                messages.success(
                    request, f"{sub.request.obligation.obligation_id} returned to the department."
                )
        except (ValidationError, InvalidTransition, ReadOnlyPeriod) as exc:
            _flash_errors(request, exc)
    nxt = request.POST.get("next", "")
    if nxt == "detail":
        return redirect("requests:detail", pk=sub.request_id)
    return redirect("requests:verify_queue")


@admin_required
def overdue(request):
    today = timezone.localdate()
    reqs = (
        EvidenceRequest.objects.with_related()
        .filter(Q(status=S.OVERDUE) | Q(status__in=AWAITING_OFFICER, due_date__lt=today))
        .annotate(notices=Count("outbox"))
        .order_by("due_date")
    )
    return render(request, "requests/overdue.html", {"items": reqs, "today": today})


# --- downloads (every role, object-level check) -----------------------------------------
def _serve(request, attachment, owning: EvidenceRequest):
    if not owning.is_visible_to(request.user):
        raise PermissionDenied  # SPEC 2 rule 1: never another department's file
    record(
        Action.FILE_DOWNLOADED,
        actor=request.user,
        obj=attachment,
        request=request,
        detail=f"Downloaded {attachment.original_filename} (sha256 {attachment.sha256}).",
    )
    return file_response(attachment)


@any_role_required
def request_attachment_download(request, pk: int):
    att = get_object_or_404(
        RequestAttachment.objects.select_related("request", "request__obligation"), pk=pk
    )
    return _serve(request, att, att.request)


@any_role_required
def submission_attachment_download(request, pk: int):
    att = get_object_or_404(
        SubmissionAttachment.objects.select_related(
            "submission__request", "submission__request__obligation"
        ),
        pk=pk,
    )
    return _serve(request, att, att.submission.request)


# --- officer ----------------------------------------------------------------------------
@officer_required
def inbox(request):
    today = timezone.localdate()
    period = ReportingPeriod.current()
    reqs = (
        EvidenceRequest.objects.visible_to(request.user)
        .with_related()
        .filter(period=period)
        .prefetch_related("attachments", _submissions_prefetch())
        .order_by("due_date")
    )
    past, todo, done = [], [], []
    for r in reqs:
        if r.status in AWAITING_OFFICER:
            (past if r.due_date < today or r.status == S.OVERDUE else todo).append(r)
        else:
            done.append(r)
    return render(
        request,
        "my/inbox.html",
        {"past": past, "todo": todo, "done": done, "period": period, "today": today},
    )


def _officer_request(request, pk: int) -> EvidenceRequest:
    req = get_object_or_404(
        EvidenceRequest.objects.with_related().prefetch_related(
            "attachments", _submissions_prefetch()
        ),
        pk=pk,
    )
    if not req.is_visible_to(request.user):
        raise PermissionDenied  # SPEC 2 rule 5: object-level, not just role
    return req


@officer_required
def submit(request, pk: int):
    req = _officer_request(request, pk)
    form = SubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not req.can_submit(request.user):
            messages.error(request, "This request cannot take a submission now.")
            return redirect("my:submit", pk=pk)
        if form.is_valid():
            try:
                services.submit(
                    req,
                    request.user,
                    form.submission_data(),
                    form.cleaned_data["files"],
                    http_request=request,
                )
            except (ValidationError, InvalidTransition, ReadOnlyPeriod) as exc:
                if isinstance(exc, ValidationError) and hasattr(exc, "error_dict"):
                    for field, errs in exc.message_dict.items():
                        form.add_error(field if field in form.fields else None, errs)
                else:
                    form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"Submitted. Regulation & Compliance will verify "
                    f"{req.obligation.obligation_id}.",
                )
                return redirect("my:inbox")
        elif "files" in form.errors:
            record(
                Action.FILE_REJECTED,
                obj=req,
                request=request,
                detail="; ".join(form.errors["files"])[:1000],
            )
    return render(
        request,
        "my/submit.html",
        {
            "req": req,
            "form": form,
            "can_submit": req.can_submit(request.user),
            "submissions": list(req.submissions.all()),
        },
    )


@officer_required
def history(request):
    subs = (
        Submission.objects.filter(request__assigned_department_id=request.user.department_id)
        .select_related(
            "request", "request__obligation", "request__period", "submitted_by", "verified_by"
        )
        .prefetch_related("attachments")
        .order_by("-submitted_at")
    )
    return render(request, "my/history.html", {"submissions": subs[:300]})


@admin_required
def officers_options(request):
    """HTMX: officer <option>s for the chosen department."""
    dept = request.GET.get("department", "")
    qs = User.objects.active().filter(role=Role.OFFICER)
    qs = qs.filter(department_id=int(dept)) if dept.isdigit() else qs.none()
    return render(request, "components/officer_options.html", {"officers": qs})
