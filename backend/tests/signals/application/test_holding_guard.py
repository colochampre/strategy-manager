"""Unit tests: ``HoldingGuard``'s precedence order (spec: capital-allocation
§ Existing-Position Guard; design.md § "Guard order"):

own reservation -> resume (skip entirely) -> in flight (raise, or abandon
past the age bound) -> flat -> proceed -> divergent -> refuse.

Fakes only -- no database; the underlying joins are proven in
``test_in_flight_work_integration.py`` and ``test_symbol_holdings_integration.py``.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.signals.application.holding_guard import (
    HoldingGuard,
    HoldingNotSettledYet,
)
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.holding import HeldAllocation

POOL: PoolKey = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
MAX_AGE_SECONDS = 600.0


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class FakeSymbolHoldingsPort:
    holdings: list[HeldAllocation] = field(default_factory=list)
    calls: list[tuple[PoolKey, str]] = field(default_factory=list)

    async def symbol_holdings(self, pool: PoolKey, symbol: str) -> list[HeldAllocation]:
        self.calls.append((pool, symbol))
        return self.holdings


@dataclass
class FakeInFlightWorkPort:
    result: bool = False
    calls: list[tuple[PoolKey, UUID, str, datetime]] = field(default_factory=list)

    async def in_flight(
        self, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool:
        self.calls.append((pool, strategy_id, symbol, now))
        return self.result


def _guard(
    *,
    holdings: FakeSymbolHoldingsPort | None = None,
    in_flight_work: FakeInFlightWorkPort | None = None,
    clock: FrozenClock | None = None,
    max_age_seconds: float = MAX_AGE_SECONDS,
) -> tuple[HoldingGuard, FakeSymbolHoldingsPort, FakeInFlightWorkPort]:
    holdings_port = holdings or FakeSymbolHoldingsPort()
    in_flight_port = in_flight_work or FakeInFlightWorkPort()
    guard = HoldingGuard(
        holdings=holdings_port,
        in_flight_work=in_flight_port,
        clock=clock or FrozenClock(NOW),
        delayed_open_max_signal_age_seconds=max_age_seconds,
    )
    return guard, holdings_port, in_flight_port


async def test_an_own_reservation_resumes_without_checking_anything() -> None:
    """The guard's FIRST precedence rung: a retried job whose earlier
    attempt already produced a reservation for this exact signal must not
    re-run the in-flight or holding checks at all."""
    holdings = FakeSymbolHoldingsPort(
        holdings=[HeldAllocation(strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("9"))]
    )
    in_flight_work = FakeInFlightWorkPort(result=True)
    guard, holdings, in_flight_work = _guard(holdings=holdings, in_flight_work=in_flight_work)

    outcome = await guard.check(
        pool=POOL,
        strategy_id=uuid4(),
        symbol="ETHUSDT",
        own_reservation_id=uuid4(),
        received_at=NOW,
    )

    assert outcome.proceed is True
    assert outcome.refused is None
    assert in_flight_work.calls == []
    assert holdings.calls == []


async def test_in_flight_within_the_age_bound_raises_holding_not_settled_yet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard, holdings, _ = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

    with pytest.raises(HoldingNotSettledYet):
        await guard.check(
            pool=POOL,
            strategy_id=uuid4(),
            symbol="ETHUSDT",
            own_reservation_id=None,
            received_at=NOW - timedelta(seconds=30),
        )

    assert holdings.calls == []


async def test_in_flight_past_the_age_bound_abandons_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = uuid4()
    guard, holdings, _ = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

    with caplog.at_level("WARNING"):
        outcome = await guard.check(
            pool=POOL,
            strategy_id=strategy_id,
            symbol="ETHUSDT",
            own_reservation_id=None,
            received_at=NOW - timedelta(seconds=MAX_AGE_SECONDS + 1),
        )

    assert outcome.proceed is False
    assert outcome.refused is not None
    assert str(strategy_id) in outcome.refused
    assert "ETHUSDT" in outcome.refused
    assert any(record.levelname == "WARNING" for record in caplog.records)
    assert holdings.calls == []


async def test_a_flat_strategy_proceeds() -> None:
    strategy_id = uuid4()
    other_strategy_holding = HeldAllocation(
        strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("0.7")
    )
    guard, holdings, in_flight_work = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[other_strategy_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
    )

    outcome = await guard.check(
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.proceed is True
    assert outcome.refused is None
    assert in_flight_work.calls == [(POOL, strategy_id, "ETHUSDT", NOW)]
    assert holdings.calls == [(POOL, "ETHUSDT")]


async def test_a_divergent_holding_refuses_with_a_warning_naming_the_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
    )

    with caplog.at_level("WARNING"):
        outcome = await guard.check(
            pool=POOL,
            strategy_id=strategy_id,
            symbol="ETHUSDT",
            own_reservation_id=None,
            received_at=NOW,
        )

    assert outcome.proceed is False
    assert outcome.refused is not None
    assert str(strategy_id) in outcome.refused
    assert "ETHUSDT" in outcome.refused
    assert str(allocation_id) in outcome.refused
    assert "0.5" in outcome.refused
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_only_the_strategys_own_net_decides_divergence() -> None:
    """A different strategy's non-zero holding on the same symbol must not
    refuse THIS strategy's open -- per strategy, not per pool."""
    strategy_id = uuid4()
    other_holding = HeldAllocation(
        strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("5")
    )
    guard, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[other_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
    )

    outcome = await guard.check(
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.proceed is True
