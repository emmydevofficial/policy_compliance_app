"""Loading obligations from the source data (JSON for the demo, the client's XLSX for real)."""

import re
from dataclasses import dataclass, field

from django.db import transaction

from apps.auditlog.services import Action, record
from apps.organisation.models import Department

from .models import Obligation, RegulatoryInstrument, RiskLevel
from .reference import DEPARTMENT_ALIASES, INSTRUMENTS, NOT_A_DEPARTMENT

RISK_MAP = {"high": RiskLevel.HIGH, "medium": RiskLevel.MEDIUM, "low": RiskLevel.LOW}
TEXT_FIELDS = ("description",)


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = []
        for label, items in (
            ("Created", self.created),
            ("Updated", self.updated),
            ("Deactivated", self.deactivated),
            ("Refused (needs a new obligation ID)", self.conflicts),
            ("Notes", self.notes),
        ):
            out.append(f"{label}: {len(items)}")
            out += [f"  {x}" for x in items]
        out.append(f"Unchanged: {len(self.unchanged)}")
        return out


def _unique_code(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    base = "".join(w[0] for w in words) if len(words) > 1 else (words[0] if words else "DEPT")
    base = base.upper()[:8] or "DEPT"
    code, n = base, 2
    while Department.objects.filter(code=code).exists():
        code, n = f"{base}{n}", n + 1
    return code


def resolve_department(
    name: str, report: SyncReport, actor=None, create: bool = True
) -> Department | None:
    name = DEPARTMENT_ALIASES.get(name.strip(), name.strip())
    if not name or name in NOT_A_DEPARTMENT:
        return None
    dept = Department.objects.filter(name__iexact=name).first()
    if dept or not create:
        return dept
    dept = Department(name=name, code=_unique_code(name))
    dept.stamp(actor)
    dept.save()
    record(
        Action.DEPARTMENT_CREATED,
        actor=actor,
        obj=dept,
        detail=f"Created while loading obligations: {name} ({dept.code}).",
    )
    report.notes.append(f"Created department '{name}' ({dept.code}), named in the source data.")
    return dept


def resolve_instrument(
    name: str, obligation_id: str, report: SyncReport, actor=None
) -> RegulatoryInstrument:
    inst = RegulatoryInstrument.objects.filter(name__iexact=name.strip()).first()
    if inst:
        return inst
    known = {n.lower(): (n, code, cit, desc) for n, code, cit, desc in INSTRUMENTS}
    if name.strip().lower() in known:
        n, code, cit, desc = known[name.strip().lower()]
    else:
        n, code, cit, desc = name.strip(), obligation_id.split("-")[0].upper(), "", ""
    inst = RegulatoryInstrument(name=n, short_code=code, citation=cit, description=desc)
    inst.stamp(actor)
    inst.save()
    report.notes.append(f"Created instrument '{n}' ({code}).")
    return inst


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def sync_obligations(
    rows: list[dict], *, actor=None, deactivate_missing: bool = False, dry_run: bool = False
) -> SyncReport:
    """Create or update obligations from rows keyed as obligations.json is. With
    `deactivate_missing`, active obligations absent from the rows are deactivated.

    Versioning (SPEC 3): an obligation whose regulatory text has changed and which already
    has requests is not edited in place, because historical submissions must keep pointing
    at the text that applied. Such rows are refused; give the new text a new obligation ID
    and the old one will be deactivated."""
    report = SyncReport()
    try:
        with transaction.atomic():
            _sync(rows, actor, deactivate_missing, report)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report


class _Rollback(Exception):
    pass


def _sync(rows, actor, deactivate_missing, report):
    seen: set[str] = set()
    for raw in rows:
        oid = _clean(raw.get("id")).upper()
        if not oid:
            continue
        seen.add(oid)
        risk = RISK_MAP.get(_clean(raw.get("risk")).lower())
        if risk is None:
            report.notes.append(f"{oid}: risk '{raw.get('risk')}' not recognised; row skipped.")
            continue
        dept = resolve_department(_clean(raw.get("dept")), report, actor)
        if dept is None:
            report.notes.append(f"{oid}: no primary department; row skipped.")
            continue
        values = {
            "instrument": resolve_instrument(_clean(raw.get("source")), oid, report, actor),
            "document_reference": _clean(raw.get("ref")),
            "category": _clean(raw.get("category")),
            "description": _clean(raw.get("description")),
            "obligation_type": _clean(raw.get("type")) or "Mandatory",
            "frequency": _clean(raw.get("frequency")),
            "primary_department": dept,
            "risk_level": risk,
            "evidence_required": _clean(raw.get("evidence")),
            "regulatory_deadline": _clean(raw.get("deadline")),
            "consequence": _clean(raw.get("notes")),
        }
        supporting = []
        for part in _clean(raw.get("supporting")).split(";"):
            d = resolve_department(part, report, actor) if part.strip() else None
            if d and d.pk != dept.pk and d not in supporting:
                supporting.append(d)

        ob = Obligation.objects.filter(obligation_id=oid).first()
        if ob is None:
            ob = Obligation(obligation_id=oid, **values)
            ob.stamp(actor)
            ob.save()
            ob.supporting_departments.set(supporting)
            record(
                Action.OBLIGATION_CREATED,
                actor=actor,
                obj=ob,
                detail=f"Loaded from source data: {values['category']}.",
            )
            report.created.append(oid)
            continue

        changed = [k for k, v in values.items() if getattr(ob, k) != v]
        sup_changed = set(ob.supporting_departments.values_list("pk", flat=True)) != {
            d.pk for d in supporting
        }
        text_changed = [k for k in changed if k in TEXT_FIELDS]
        if text_changed and ob.requests.exists():
            report.conflicts.append(
                f"{oid}: regulatory text changed but the obligation has request history."
            )
            continue
        if not changed and not sup_changed and ob.is_active:
            report.unchanged.append(oid)
            continue
        for k in changed:
            setattr(ob, k, values[k])
        reactivated = not ob.is_active
        ob.is_active = True
        ob.stamp(actor)
        ob.save()
        ob.supporting_departments.set(supporting)
        what = ", ".join(changed + (["supporting departments"] if sup_changed else []))
        record(
            Action.OBLIGATION_UPDATED,
            actor=actor,
            obj=ob,
            detail=f"Updated from source data: {what or 'reactivated'}"
            f"{' (reactivated)' if reactivated else ''}.",
        )
        report.updated.append(f"{oid} ({what or 'reactivated'})")

    if deactivate_missing:
        for ob in Obligation.objects.active().exclude(obligation_id__in=seen):
            ob.is_active = False
            ob.stamp(actor)
            ob.save()
            record(
                Action.OBLIGATION_DEACTIVATED,
                actor=actor,
                obj=ob,
                detail="Not present in the imported workbook; deactivated.",
            )
            report.deactivated.append(ob.obligation_id)
