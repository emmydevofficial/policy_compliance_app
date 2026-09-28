from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.accounts.services import send_invitation
from apps.core.permissions import admin_required

from . import services
from .forms import DepartmentForm, PeopleImportForm, PersonForm, ReassignBeforeDeactivateForm
from .models import Department


def _errors(exc: ValidationError) -> list[str]:
    if hasattr(exc, "message_dict"):
        return [m for ms in exc.message_dict.values() for m in ms]
    return exc.messages


# --- departments ------------------------------------------------------------------------
@admin_required
def departments(request):
    show = request.GET.get("show", "active")
    qs = Department.objects.select_related("gm").annotate(
        people=Count("members", filter=Q(members__is_active=True), distinct=True),
        open_requests=Count(
            "requests",
            filter=Q(
                requests__status__in=("DRAFT", "AWAITING", "SUBMITTED", "OVERDUE", "RETURNED")
            ),
            distinct=True,
        ),
    )
    if show == "active":
        qs = qs.filter(is_active=True)
    elif show == "inactive":
        qs = qs.filter(is_active=False)
    return render(request, "admin_area/departments.html", {"departments": qs, "show": show})


@admin_required
def department_edit(request, pk: int | None = None):
    dept = get_object_or_404(Department, pk=pk) if pk else Department()
    form = DepartmentForm(request.POST or None, instance=dept)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_department(form.save(commit=False), request.user, http_request=request)
        except ValidationError as exc:
            for m in _errors(exc):
                form.add_error(None, m)
        else:
            messages.success(request, f"{dept.name} saved.")
            return redirect("admin_area:departments")
    return render(request, "admin_area/department_form.html", {"form": form, "dept": dept})


@admin_required
@require_POST
def department_deactivate(request, pk: int):
    dept = get_object_or_404(Department, pk=pk)
    try:
        services.deactivate_department(dept, request.user, http_request=request)
    except ValidationError as exc:
        for m in _errors(exc):
            messages.error(request, m)
    else:
        messages.success(request, f"{dept.name} deactivated.")
    return redirect("admin_area:departments")


@admin_required
@require_POST
def department_reactivate(request, pk: int):
    dept = get_object_or_404(Department, pk=pk)
    services.reactivate_department(dept, request.user, http_request=request)
    messages.success(request, f"{dept.name} reactivated.")
    return redirect("admin_area:departments")


# --- people -----------------------------------------------------------------------------
@admin_required
def people(request):
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    dept = request.GET.get("department", "")
    show = request.GET.get("show", "active")
    qs = User.objects.select_related("department").order_by("full_name")
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) | Q(email__icontains=q) | Q(job_title__icontains=q)
        )
    if role in Role.values:
        qs = qs.filter(role=role)
    if dept.isdigit():
        qs = qs.filter(department_id=int(dept))
    if show == "active":
        qs = qs.filter(is_active=True)
    elif show == "inactive":
        qs = qs.filter(is_active=False)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "admin_area/people.html",
        {
            "page": page,
            "q": q,
            "role": role,
            "department": dept,
            "show": show,
            "roles": Role.choices,
            "departments": Department.objects.active(),
        },
    )


@admin_required
def person_edit(request, pk: int | None = None):
    person = get_object_or_404(User, pk=pk) if pk else User()
    old_role, old_dept = person.role, person.department_id
    form = PersonForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        try:
            if pk:
                services.update_person(
                    user,
                    request.user,
                    old_role=old_role,
                    old_department_id=old_dept,
                    http_request=request,
                )
                messages.success(request, f"{user.full_name} saved.")
            else:
                services.create_person(user, request.user, http_request=request)
                messages.success(
                    request,
                    f"{user.full_name} added. An activation link valid "
                    "for 72 hours has been emailed to them.",
                )
        except ValidationError as exc:
            for m in _errors(exc):
                form.add_error(None, m)
        else:
            return redirect("admin_area:people")
    return render(request, "admin_area/person_form.html", {"form": form, "person": person})


@admin_required
def person_deactivate(request, pk: int):
    person = get_object_or_404(User, pk=pk)
    open_reqs = list(
        services.open_requests_for_person(person).select_related(
            "obligation", "assigned_department"
        )
    )
    form = ReassignBeforeDeactivateForm(request.POST or None, requests=open_reqs)
    if request.method == "POST" and form.is_valid():
        try:
            services.deactivate_person(
                person, request.user, reassign_to=form.mapping(), http_request=request
            )
        except ValidationError as exc:
            for m in _errors(exc):
                form.add_error(None, m)
        else:
            messages.success(request, f"{person.full_name} deactivated.")
            return redirect("admin_area:people")
    return render(
        request,
        "admin_area/person_deactivate.html",
        {
            "person": person,
            "open_requests": open_reqs,
            "form": form,
        },
    )


@admin_required
@require_POST
def person_reactivate(request, pk: int):
    person = get_object_or_404(User, pk=pk)
    services.reactivate_person(person, request.user, http_request=request)
    messages.success(request, f"{person.full_name} reactivated.")
    return redirect("admin_area:people")


@admin_required
@require_POST
def person_invite(request, pk: int):
    person = get_object_or_404(User, pk=pk, is_active=True)
    send_invitation(person, request.user, http_request=request)
    messages.success(request, f"A new activation link has been sent to {person.email}.")
    return redirect("admin_area:people")


@admin_required
def people_import(request):
    report = None
    form = PeopleImportForm()
    if request.method == "POST":
        if request.POST.get("confirm") and request.session.get("people_csv"):
            text = request.session.pop("people_csv")
            report = services.import_people(text, request.user, dry_run=False, http_request=request)
            if report.ok:
                messages.success(
                    request,
                    f"Import complete: {len(report.create)} created, {len(report.update)} updated.",
                )
                return redirect("admin_area:people")
        else:
            form = PeopleImportForm(request.POST, request.FILES)
            if form.is_valid():
                text = form.cleaned_data["file"]
                report = services.import_people(text, request.user, dry_run=True)
                if report.ok:
                    request.session["people_csv"] = text
    return render(request, "admin_area/people_import.html", {"form": form, "report": report})
