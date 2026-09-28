"""SPEC 3: every allowed transition succeeds and every disallowed one raises."""

import itertools

import pytest

from apps.workflow.models import (
    TRANSITIONS,
    EvidenceRequest,
    InvalidTransition,
    RequestStatus,
)

S = RequestStatus
ALLOWED = {
    (S.DRAFT, S.AWAITING),
    (S.AWAITING, S.SUBMITTED),
    (S.AWAITING, S.OVERDUE),
    (S.OVERDUE, S.SUBMITTED),
    (S.SUBMITTED, S.VERIFIED),
    (S.SUBMITTED, S.RETURNED),
    (S.RETURNED, S.SUBMITTED),
    (S.RETURNED, S.OVERDUE),
} | {(s, S.CLOSED_NA) for s in S.values if s != S.CLOSED_NA}

PAIRS = list(itertools.product(S.values, S.values))


def test_the_table_is_exactly_the_spec():
    table = {(a, b) for a, targets in TRANSITIONS.items() for b in targets}
    assert table == ALLOWED


@pytest.mark.parametrize(("current", "new"), PAIRS, ids=[f"{a}->{b}" for a, b in PAIRS])
def test_transition_pair(current, new):
    req = EvidenceRequest(status=current)
    if (current, new) in ALLOWED:
        req.transition_to(new)
        assert req.status == new
    else:
        with pytest.raises(InvalidTransition):
            req.transition_to(new)
        assert req.status == current
