"""Departments and people (SPEC 6). Every action writes an AuditEvent."""

import csv
import io
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import NotificationPreference, Role, User
from apps.accounts.services import send_invitation
from apps.auditlog.services import Action, record
from apps.workflow.models import OPEN_STATUSES, EvidenceRequest

from .models import Department


def open_requests_for_department(dept: Department):
    return EvidenceRequest.objects.filter(assigned_department=dept, status__in=OPEN_STATUSES)


def open_requests_for_person(user: User):
    return EvidenceRequest.objects.filter(assigned_officer=user, status__in=OPEN_STATUSES)


# --- departments ------------------------------------------------------------------------
@transaction.atomic
def save_department(dept: Department, actor: User, *, http_request=None) -> Department:
    creating = dept.pk is None
    dept.stamp(actor)
    dept.full_clean()
    dept.save()
    if dept.gm_id and dept.gm.department_id == dept.pk and not dept.gm.is_department_gm:
        dept.gm.is_department_gm = True
        dept.gm.save(update_fields=["is_department_gm"])
    record(
        Action.DEPARTMENT_CREATED if creating else Action.DEPARTMENT_UPDATED,
        actor=actor,
        obj=dept,
        request=http_request,
        detail=f"{dept.name} ({dept.code}); GM: {dept.gm.full_name if dept.gm else 'none'}.",
    )
    return dept


@transaction.atomic
def deactivate_department(dept: Department, actor: User, *, http_request=None) -> Department:
    blocking = list(open_requests_for_department(dept).select_related("obligation"))
    if blocking:
        names = ", ".join(r.obligation.obligation_id for r in blocking)
        raise ValidationError(
            f"{dept.name} has {len(blocking)} open request(s): {names}. Reassign or close them "
            "before deactivating the department."
        )
    dept.is_active = False
    dept.stamp(actor)
    dept.save()
    record(
        Action.DEPARTMENT_DEACTIVATED,
        actor=actor,
        obj=dept,
        request=http_request,
        detail=f"{dept.name} deactivated.",
    )
    return dept


@transaction.atomic
def reactivate_department(dept: Department, actor: User, *, http_request=None) -> Department:
    dept.is_active = True
    dept.stamp(actor)
    dept.save()
    record(
        Action.DEPARTMENT_REACTIVATED,
        actor=actor,
        obj=dept,
        request=http_request,
        detail=f"{dept.name} reactivated.",
    )
    return dept


# --- people -----------------------------------------------------------------------------
@transaction.atomic
def create_person(user: User, actor: User, *, http_request=None) -> User:
    user.email = user.email.lower()
    user.set_unusable_password()
    user.stamp(actor)
    user.full_clean(exclude=["password"])
    user.save()
    NotificationPreference.objects.get_or_create(user=user)
    record(
        Action.USER_CREATED,
        actor=actor,
        obj=user,
        request=http_request,
        detail=f"{user.full_name} <{user.email}>, {user.get_role_display()}"
        f"{', ' + user.department.name if user.department else ''}"
        f"{', department GM' if user.is_department_gm else ''}.",
    )
    send_invitation(user, actor, http_request=http_request)
    return user


@transaction.atomic
def update_person(
    user: User, actor: User, *, old_role: str, old_department_id, http_request=None
) -> User:
    if user.pk == actor.pk and user.role != Role.ADMIN:
        raise ValidationError("You cannot remove your own Admin role.")
    if old_department_id and old_department_id != user.department_id:
        blocking = list(open_requests_for_person(user).select_related("obligation"))
        if blocking:
            raise ValidationError(
                "Reassign this person's open requests before moving them to another "
                "department: " + ", ".join(r.obligation.obligation_id for r in blocking)
            )
    user.stamp(actor)
    user.full_clean(exclude=["password"])
    user.save()
    record(
        Action.USER_UPDATED,
        actor=actor,
        obj=user,
        request=http_request,
        detail=f"Details updated for {user.full_name}.",
    )
    if old_role != user.role:
        record(
            Action.ROLE_CHANGED,
            actor=actor,
            obj=user,
            request=http_request,
            detail=f"Role changed from {old_role} to {user.role}.",
        )
    return user


@transaction.atomic
def deactivate_person(
    user: User, actor: User, *, reassign_to: dict[int, User] | None = None, http_request=None
) -> User:
    """Deactivating someone with open requests requires reassigning those requests first.
    `reassign_to` maps request id to the new officer."""
    from apps.workflow.services import reassign

    if user.pk == actor.pk:
        raise ValidationError("You cannot deactivate your own account.")
    reassign_to = reassign_to or {}
    blocking = list(
        open_requests_for_person(user).select_related("obligation", "assigned_department")
    )
    missing = [r for r in blocking if r.pk not in reassign_to]
    if missing:
        raise ValidationError(
            "Reassign these open requests first: "
            + ", ".join(r.obligation.obligation_id for r in missing)
        )
    for req in blocking:
        new = reassign_to[req.pk]
        reassign(
            req,
            req.assigned_department,
            new,
            f"{user.full_name} deactivated; reassigned to {new.full_name}.",
            actor,
            http_request=http_request,
        )
    user.is_active = False
    user.stamp(actor)
    user.save()
    Department.objects.filter(gm=user).update(gm=None)
    record(
        Action.USER_DEACTIVATED,
        actor=actor,
        obj=user,
        request=http_request,
        detail=f"{user.full_name} deactivated"
        f"{f'; {len(blocking)} request(s) reassigned' if blocking else ''}.",
    )
    return user


@transaction.atomic
def reactivate_person(user: User, actor: User, *, http_request=None) -> User:
    user.is_active = True
    user.stamp(actor)
    user.save()
    record(
        Action.USER_REACTIVATED,
        actor=actor,
        obj=user,
        request=http_request,
        detail=f"{user.full_name} reactivated.",
    )
    return user


# --- bulk import ------------------------------------------------------------------------
PEOPLE_CSV_COLUMNS = [
    "full_name",
    "email",
    "job_title",
    "phone",
    "role",
    "department_code",
    "is_department_gm",
]


@dataclass
class ImportReport:
    create: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "y", "yes", "true", "gm")


def import_people(text: str, actor: User, *, dry_run: bool, http_request=None) -> ImportReport:
    """CSV with columns PEOPLE_CSV_COLUMNS. The dry run reports what would change and writes
    nothing. A live run refuses to write anything if any row has an error."""
    report = ImportReport()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in ("full_name", "email", "role") if c not in cols]
    if missing:
        report.errors.append(
            f"Missing columns: {', '.join(missing)}. Expected: {', '.join(PEOPLE_CSV_COLUMNS)}."
        )
        return report
    depts = {d.code.upper(): d for d in Department.objects.all()}
    planned: list[tuple[User, bool, str | None]] = []
    seen: set[str] = set()
    for n, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        email = row.get("email", "").lower()
        if not email:
            report.errors.append(f"Line {n}: no email.")
            continue
        if email in seen:
            report.errors.append(f"Line {n}: {email} appears twice.")
            continue
        seen.add(email)
        role = row.get("role", "").upper()
        if role not in Role.values:
            report.errors.append(
                f"Line {n}: role '{row.get('role')}' is not ADMIN, OFFICER or EXECUTIVE."
            )
            continue
        code = row.get("department_code", "").upper()
        dept = depts.get(code) if code else None
        if code and dept is None:
            report.errors.append(f"Line {n}: no department with code {code}.")
            continue
        existing = User.objects.filter(email=email).first()
        user = existing or User(email=email)
        old_role = existing.role if existing else None
        values = {
            "full_name": row.get("full_name", ""),
            "job_title": row.get("job_title", ""),
            "phone": row.get("phone", ""),
            "role": role,
            "department": dept,
            "is_department_gm": _truthy(row.get("is_department_gm", "")),
        }
        changes = [k for k, v in values.items() if getattr(user, k) != v] if existing else []
        for k, v in values.items():
            setattr(user, k, v)
        try:
            user.full_clean(exclude=["password"], validate_unique=False)
        except ValidationError as exc:
            msgs = "; ".join(m for ms in exc.message_dict.values() for m in ms)
            report.errors.append(f"Line {n} ({email}): {msgs}")
            continue
        if existing is None:
            report.create.append(
                f"{values['full_name']} <{email}> as {role}{' in ' + dept.name if dept else ''}"
            )
            planned.append((user, True, None))
        elif changes:
            report.update.append(f"{email}: {', '.join(changes)}")
            planned.append((user, False, old_role))
        else:
            report.unchanged.append(email)

    if dry_run or not report.ok:
        return report
    with transaction.atomic():
        for user, is_new, old_role in planned:
            if is_new:
                create_person(user, actor, http_request=http_request)
            else:
                update_person(
                    user,
                    actor,
                    old_role=old_role,
                    old_department_id=User.objects.get(pk=user.pk).department_id,
                    http_request=http_request,
                )
        record(
            Action.PEOPLE_IMPORTED,
            actor=actor,
            object_type="User",
            request=http_request,
            detail=f"CSV import: {len(report.create)} created, {len(report.update)} updated.",
        )
    return report
