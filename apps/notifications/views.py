from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateSyntaxError
from django.views.decorators.http import require_POST

from apps.auditlog.services import Action, record
from apps.core.permissions import admin_required

from .forms import HolidayForm, ReminderRuleForm, TemplateForm
from .models import Holiday, NotificationOutbox, NotificationTemplate, ReminderRule
from .rendering import DIGEST_PLACEHOLDER, PLACEHOLDERS, render_notice

SAMPLE = {
    "officer_name": "Ngozi Eze",
    "department_name": "HSE",
    "obligation_id": "HSC-003",
    "obligation_text": "Report every serious accident to NERC within 24 hours.",
    "instrument": "Nigeria Electricity H&S Code 2014",
    "document_reference": "Section 4.2",
    "risk_level": "High",
    "evidence_list": "- Incident report\n- NERC acknowledgement",
    "deadline": "Friday 16 October 2026",
    "days_remaining": 7,
    "days_overdue": 3,
    "consequence": "Fines and sanctions under the Electricity Act 2023.",
    "upload_link": "https://obligationdesk.example.org/my/requests/47/",
    "gm_name": "Babatunde Adeyemi",
    "period_name": "Q4 2026",
    "reason": "The report attached is unsigned.",
    DIGEST_PLACEHOLDER: "- HSC-003: Overdue, due 02 Oct 2026\n- HSC-005: Awaiting, due 30 Oct 2026",
}


@admin_required
def reminders(request):
    rule = ReminderRule.get()
    before = {f: getattr(rule, f) for f in ["days_before", *ReminderRuleForm.Meta.fields]}
    form = ReminderRuleForm(request.POST or None, instance=rule, prefix="r")
    holiday_form = HolidayForm(prefix="h")
    if request.method == "POST" and form.is_valid():
        rule = form.save(commit=False)
        rule.stamp(request.user)
        rule.save()
        changes = [
            f"{k}: {v} → {getattr(rule, k)}" for k, v in before.items() if getattr(rule, k) != v
        ]
        record(
            Action.REMINDER_RULE_CHANGED,
            actor=request.user,
            obj=rule,
            request=request,
            detail="; ".join(changes) or "Saved without changes.",
        )
        messages.success(request, "Reminder rules saved.")
        return redirect("admin_area:reminders")
    return render(
        request,
        "admin_area/reminders.html",
        {
            "form": form,
            "holiday_form": holiday_form,
            "holidays": Holiday.objects.all(),
            "failed": NotificationOutbox.objects.filter(status="FAILED")[:20],
        },
    )


@admin_required
@require_POST
def holiday_add(request):
    form = HolidayForm(request.POST, prefix="h")
    if form.is_valid():
        h = form.save(commit=False)
        h.stamp(request.user)
        h.save()
        record(
            Action.REMINDER_RULE_CHANGED,
            actor=request.user,
            obj=h,
            request=request,
            detail=f"Holiday added: {h}.",
        )
        messages.success(request, f"Holiday added: {h}.")
    else:
        for es in form.errors.values():
            for e in es:
                messages.error(request, e)
    return redirect("admin_area:reminders")


@admin_required
@require_POST
def holiday_remove(request, pk: int):
    h = get_object_or_404(Holiday, pk=pk)
    label = str(h)
    h.delete()
    record(
        Action.REMINDER_RULE_CHANGED,
        actor=request.user,
        object_type="Holiday",
        object_id=str(pk),
        request=request,
        detail=f"Holiday removed: {label}.",
    )
    messages.success(request, f"Holiday removed: {label}.")
    return redirect("admin_area:reminders")


@admin_required
def templates(request):
    return render(
        request, "admin_area/templates.html", {"templates": NotificationTemplate.objects.all()}
    )


@admin_required
def template_edit(request, pk: int):
    tpl = get_object_or_404(NotificationTemplate, pk=pk)
    old = (tpl.subject_template, tpl.body_template, tpl.is_active)
    form = TemplateForm(request.POST or None, instance=tpl)
    if request.method == "POST" and form.is_valid():
        tpl = form.save(commit=False)
        tpl.stamp(request.user)
        tpl.save()
        what = [
            n
            for n, a, b in zip(
                ("subject", "body", "active flag"),
                old,
                (tpl.subject_template, tpl.body_template, tpl.is_active),
                strict=True,
            )
            if a != b
        ]
        record(
            Action.TEMPLATE_EDITED,
            actor=request.user,
            obj=tpl,
            request=request,
            detail=f"Template {tpl.key} edited: {', '.join(what) or 'no change'}.",
        )
        messages.success(
            request, f"{tpl.name} saved. Notices already sent keep the wording they were sent with."
        )
        return redirect("admin_area:templates")
    return render(
        request,
        "admin_area/template_form.html",
        {
            "form": form,
            "tpl": tpl,
            "placeholders": PLACEHOLDERS,
            "digest": tpl.key == "weekly_digest",
            "digest_placeholder": DIGEST_PLACEHOLDER,
        },
    )


@admin_required
@require_POST
def template_preview(request, pk: int):
    """HTMX: render the unsaved template text against sample data."""
    tpl = get_object_or_404(NotificationTemplate, pk=pk)
    draft = NotificationTemplate(
        key=tpl.key,
        name=tpl.name,
        subject_template=request.POST.get("subject_template", ""),
        body_template=request.POST.get("body_template", ""),
    )
    try:
        subject, body, _ = render_notice(draft, SAMPLE)
        error = ""
    except TemplateSyntaxError as exc:
        subject, body, error = "", "", str(exc)
    return render(
        request,
        "components/email_preview.html",
        {"subject": subject, "body": body, "error": error, "sample": True},
    )
