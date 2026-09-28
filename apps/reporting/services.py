"""Figures for the dashboards and the quarterly report, computed in a few queries."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone

from apps.obligations.models import Obligation
from apps.workflow.models import (
    COMPLIANCE_CSS,
    ComplianceStatus,
    EvidenceRequest,
    ReportingPeriod,
    RequestStatus,
    Submission,
)

S = RequestStatus
OUTSTANDING = (S.AWAITING, S.OVERDUE, S.RETURNED)
NOT_SUBMITTED = "NOT_SUBMITTED"


@dataclass
class Row:
    """One obligation with its request (if any) in the period."""

    ob: Obligation
    req: EvidenceRequest | None
    sub: Submission | None

    @property
    def position(self) -> str:
        """Compliance position: the current submission's status, or NOT_SUBMITTED / CLOSED."""
        if self.req is None:
            return "NO_REQUEST"
        if self.req.status == S.CLOSED_NA:
            return ComplianceStatus.NOT_APPLICABLE
        if self.sub is None:
            return NOT_SUBMITTED
        return self.sub.compliance_status

    @property
    def fully_compliant(self) -> bool:
        return (
            self.req is not None
            and self.req.status == S.VERIFIED
            and self.sub is not None
            and self.sub.compliance_status == ComplianceStatus.COMPLIANT
        )

    @property
    def needs_action_plan(self) -> bool:
        return self.sub is not None and self.sub.compliance_status in (
            ComplianceStatus.PARTIALLY_COMPLIANT,
            ComplianceStatus.NON_COMPLIANT,
        )


POSITION_LABELS = {
    **dict(ComplianceStatus.choices),
    NOT_SUBMITTED: "Not yet submitted",
    "NO_REQUEST": "No request issued",
}
POSITION_CSS = {**COMPLIANCE_CSS, NOT_SUBMITTED: "warn", "NO_REQUEST": "na"}


def period_rows(period: ReportingPeriod | None) -> list[Row]:
    reqs = (
        EvidenceRequest.objects.filter(period=period)
        .select_related("assigned_department", "assigned_officer")
        .prefetch_related(
            Prefetch(
                "submissions",
                queryset=Submission.objects.select_related("submitted_by").prefetch_related(
                    "attachments"
                ),
            )
        )
    )
    by_ob = {r.obligation_id: r for r in reqs}
    obs = (
        Obligation.objects.active()
        .select_related("instrument", "primary_department")
        .prefetch_related("supporting_departments")
        .order_by("obligation_id")
    )
    out = []
    for ob in obs:
        req = by_ob.get(ob.pk)
        if req is not None:
            req.obligation = ob
        out.append(Row(ob=ob, req=req, sub=req.current_submission if req else None))
    return out


@dataclass
class Breakdown:
    label: str
    total: int = 0
    verified: int = 0
    compliant: int = 0
    submitted: int = 0
    outstanding: int = 0
    overdue: int = 0
    returned: int = 0
    closed: int = 0
    no_request: int = 0

    @property
    def pct_compliant(self) -> int:
        base = self.total - self.closed
        return round(100 * self.compliant / base) if base else 0

    def add(self, row: Row) -> None:
        self.total += 1
        if row.req is None:
            self.no_request += 1
            return
        st = row.req.status
        self.verified += st == S.VERIFIED
        self.compliant += row.fully_compliant
        self.submitted += st == S.SUBMITTED
        self.outstanding += st in OUTSTANDING
        self.overdue += st == S.OVERDUE
        self.returned += st == S.RETURNED
        self.closed += st == S.CLOSED_NA


@dataclass
class Summary:
    period: ReportingPeriod | None
    rows: list[Row]
    positions: list[tuple[str, str, str, int]] = field(default_factory=list)
    by_department: list[Breakdown] = field(default_factory=list)
    by_instrument: list[Breakdown] = field(default_factory=list)
    overall: Breakdown = field(default_factory=lambda: Breakdown("All"))
    overdue: int = 0
    due_soon: int = 0
    awaiting_verification: int = 0
    high_risk: int = 0
    high_risk_overdue: list[Row] = field(default_factory=list)
    high_risk_exposure: list[Row] = field(default_factory=list)
    action_plans: list[Row] = field(default_factory=list)
    licence_exposure: list[Row] = field(default_factory=list)


def summarise(period: ReportingPeriod | None = None) -> Summary:
    period = period or ReportingPeriod.current()
    rows = period_rows(period)
    today = timezone.localdate()
    s = Summary(period=period, rows=rows)
    counts = Counter(r.position for r in rows)
    order = [*ComplianceStatus.values, NOT_SUBMITTED, "NO_REQUEST"]
    s.positions = [(k, POSITION_LABELS[k], POSITION_CSS[k], counts.get(k, 0)) for k in order]
    depts: dict[str, Breakdown] = defaultdict(lambda: Breakdown(""))
    insts: dict[str, Breakdown] = defaultdict(lambda: Breakdown(""))
    for r in rows:
        dname = r.req.assigned_department.name if r.req else r.ob.primary_department.name
        depts[dname].label = dname
        depts[dname].add(r)
        insts[r.ob.instrument.name].label = r.ob.instrument.name
        insts[r.ob.instrument.name].add(r)
        s.overall.add(r)
        high = r.ob.risk_level == "HIGH"
        s.high_risk += high
        if r.req:
            st = r.req.status
            s.overdue += st == S.OVERDUE
            s.awaiting_verification += st == S.SUBMITTED
            if st in (S.AWAITING, S.RETURNED) and today <= r.req.due_date <= today + timedelta(7):
                s.due_soon += 1
            if high and st == S.OVERDUE:
                s.high_risk_overdue.append(r)
        if (
            high
            and not r.fully_compliant
            and r.position not in (ComplianceStatus.NOT_APPLICABLE,)
            and (r.req is None or r.req.status in (*OUTSTANDING,) or r.needs_action_plan)
        ):
            s.high_risk_exposure.append(r)
        if r.needs_action_plan:
            s.action_plans.append(r)
        if (
            r.ob.instrument.short_code == "LIC"
            and not r.fully_compliant
            and (r.position != ComplianceStatus.NOT_APPLICABLE)
        ):
            s.licence_exposure.append(r)
    s.by_department = sorted(depts.values(), key=lambda b: b.label)
    s.by_instrument = sorted(insts.values(), key=lambda b: b.label)
    s.high_risk_overdue.sort(key=lambda r: r.req.due_date)
    return s
