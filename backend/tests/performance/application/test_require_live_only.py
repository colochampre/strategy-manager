"""Unit tests: ``require_live_only`` -- the second wall that keeps a rehearsal
group out of every total (design.md, addendum "a strategy's operations",
section C).

The first wall is by construction: the totals read ``PoolFills.groups`` and
nothing else. This one is by refusal: a source that puts a rehearsal group in
the live set ends as an ``InvariantViolation`` (the router's fixed 500 and one
ERROR), never as a figure.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.application.scope import require_live_only
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.shared.domain.errors import InvariantViolation

AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _group(allocation_id: UUID, side: str, *, rehearsal: bool) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="SOLUSDT.P",
        side=side,
        fee_currency="USDT",
        quantity=Decimal("1"),
        notional=Decimal("100"),
        fee=Decimal("0"),
        first_filled_at=AT,
        last_filled_at=AT,
        pool_total_at_open=Decimal("1000"),
        rehearsal=rehearsal,
    )


def _raised(call: Callable[[], object]) -> BaseException | None:
    """The exception a call raised, or ``None``: lets the test assert on the
    exception's type, so a missing refusal fails on an assertion."""
    try:
        call()
    except Exception as error:
        return error
    return None


def test_a_rehearsal_group_in_the_live_set_is_refused_naming_the_allocation() -> None:
    live, dry = uuid4(), uuid4()
    groups = (
        _group(live, "BUY", rehearsal=False),
        _group(dry, "BUY", rehearsal=True),
    )

    error = _raised(lambda: require_live_only(groups))

    assert type(error) is InvariantViolation
    assert str(dry) in str(error)
    assert str(live) not in str(error)


def test_a_live_set_without_rehearsal_groups_is_accepted() -> None:
    a, b = uuid4(), uuid4()
    groups = (
        _group(a, "BUY", rehearsal=False),
        _group(a, "SELL", rehearsal=False),
        _group(b, "BUY", rehearsal=False),
    )

    assert _raised(lambda: require_live_only(groups)) is None
    assert _raised(lambda: require_live_only(())) is None
