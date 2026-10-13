"""T5, the net for display agrees with the fold (design addendum "open
positions", sections D and K row 9).

The figures' net is the guard's arithmetic written a second time, for display
only; the DECISION that a row exists is the fold's. This is what keeps the two
from drifting apart: over T2's generated ledgers, ``open_position_figures``
answers figures with a size above zero exactly when the fold calls the
allocation open AND its symbol resolves. Where they would disagree, a row would
show ``INCONSISTENT`` (K row 9), and this test is what keeps that from arising.
"""

import pytest

from strategy_manager.execution.domain.mode_origin import fold_open_allocations
from strategy_manager.performance.domain.open_position import (
    FiguresMissing,
    OpenPositionFigures,
    open_position_figures,
)
from tests.performance.generated_ledger import (
    BASE,
    GeneratedAllocation,
    GeneratedState,
    generate_states,
)

STATES = generate_states()
ALLOCATIONS = [(s.index, a) for s in STATES for a in s.allocations]


def test_the_generated_ledgers_include_the_allocations_the_base_fee_rule_decides() -> None:
    """The rule is only exercised by an allocation whose purchase a base-currency
    fee shrank to exactly nothing: flat for the fold, open if the fee were
    ignored."""
    flat_through_the_fee = [
        a
        for _, a in ALLOCATIONS
        if not fold_open_allocations(a.ledger_groups())
        and any(f.fee_currency.upper() == BASE and f.fee > 0 for f in a.fills)
    ]
    held = [a for _, a in ALLOCATIONS if fold_open_allocations(a.ledger_groups())]
    unresolved = [a for a in held if not a.resolves]

    assert len(flat_through_the_fee) > 10
    assert len(held) > 300
    assert len(unresolved) > 10


@pytest.mark.parametrize("state", STATES, ids=[f"state-{s.index}" for s in STATES])
def test_figures_with_a_size_exist_exactly_when_the_fold_calls_the_allocation_open(
    state: GeneratedState,
) -> None:
    for allocation in state.allocations:
        _check(state.index, allocation)


def _check(index: int, allocation: GeneratedAllocation) -> None:
    fold_says_open = bool(fold_open_allocations(allocation.ledger_groups()))

    result = open_position_figures(allocation.aggregates())

    shows_a_size = isinstance(result, OpenPositionFigures) and result.size > 0
    assert shows_a_size == (fold_says_open and allocation.resolves), (
        f"state {index}, allocation {allocation.allocation_id}: the fold says "
        f"{'open' if fold_says_open else 'flat'}, the symbol "
        f"{'resolves' if allocation.resolves else 'does not resolve'}, and the figures "
        f"answered {result!r}"
    )
    if not allocation.resolves and fold_says_open:
        assert result is FiguresMissing.UNRESOLVED_SYMBOL
