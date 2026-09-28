"""Reporting periods: the GM's office opens and closes quarters without a developer."""

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditlog.services import Action, record
from apps.core.permissions import admin_required

from .models import ReportingPeriod


class PeriodForm(forms.ModelForm):
    class Meta:
        model = ReportingPeriod
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


@admin_required
def periods(request):
    form = PeriodForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.is_open = False
        p.stamp(request.user)
        p.save()
        record(
            Action.PERIOD_CHANGED,
            actor=request.user,
            obj=p,
            request=request,
            detail=f"Period {p.name} created ({p.start_date} to {p.end_date}), closed.",
        )
        messages.success(request, f"{p.name} created. Open it when it should take requests.")
        return redirect("admin_area:periods")
    return render(
        request, "admin_area/periods.html", {"periods": ReportingPeriod.objects.all(), "form": form}
    )


@admin_required
@require_POST
def period_toggle(request, pk: int):
    p = get_object_or_404(ReportingPeriod, pk=pk)
    try:
        with transaction.atomic():
            if p.is_open:
                p.is_open = False
                verb = "closed. Its requests are now read-only for everyone"
            else:
                p.is_open = True
                p.full_clean()
                verb = "opened"
            p.stamp(request.user)
            p.save()
            record(
                Action.PERIOD_CHANGED,
                actor=request.user,
                obj=p,
                request=request,
                detail=f"Period {p.name} {verb}.",
            )
    except ValidationError as exc:
        for m in exc.messages:
            messages.error(request, m)
    else:
        messages.success(request, f"{p.name} {verb}.")
    return redirect("admin_area:periods")
