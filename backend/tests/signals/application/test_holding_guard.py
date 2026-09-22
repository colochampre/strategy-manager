"""Unit tests: ``HoldingGuard``'s precedence order (spec: capital-allocation
§ Existing-Position Guard; design.md § "Guard order"):

own reservation -> resume (skip entirely) -> in flight (raise, or abandon
past the age bound) -> flat -> proceed -> divergent -> classify (S4) ->
refuse.

Fakes only -- no database; the underlying joins are proven in
``test_in_flight_work_integration.py`` and ``test_symbol_holdings_integration.py``.
The venue read itself is proven in ``test_venue_net_position.py``; here it is
a fake, so these tests exercise only the guard's OWN wiring: which branch
reads the venue at all, and what ``classify_orphan``'s outcome does to the
refusal.
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


@dataclass
class FakeVenueNetPositionPort:
    """Stands in for ``VenueNetPositionAdapter``. ``net`` is what a real read
    would have answered; ``None`` rehearses the "read failed" case the port
    itself never raises for."""

    net: Decimal | None = None
    calls: list[tuple[PoolKey, str]] = field(default_factory=list)

    async def net_position(self, pool: PoolKey, symbol: str) -> Decimal | None:
        self.calls.append((pool, symbol))
        return self.net


def _guard(
    *,
    holdings: FakeSymbolHoldingsPort | None = None,
    in_flight_work: FakeInFlightWorkPort | None = None,
    venue_net_position: FakeVenueNetPositionPort | None = None,
    clock: FrozenClock | None = None,
    max_age_seconds: float = MAX_AGE_SECONDS,
) -> tuple[HoldingGuard, FakeSymbolHoldingsPort, FakeInFlightWorkPort, FakeVenueNetPositionPort]:
    holdings_port = holdings or FakeSymbolHoldingsPort()
    in_flight_port = in_flight_work or FakeInFlightWorkPort()
    venue_port = venue_net_position or FakeVenueNetPositionPort()
    guard = HoldingGuard(
        holdings=holdings_port,
        in_flight_work=in_flight_port,
        venue_net_position=venue_port,
        clock=clock or FrozenClock(NOW),
        delayed_open_max_signal_age_seconds=max_age_seconds,
    )
    return guard, holdings_port, in_flight_port, venue_port


async def test_an_own_reservation_resumes_without_checking_anything() -> None:
    """The guard's FIRST precedence rung: a retried job whose earlier
    attempt already produced a reservation for this exact signal must not
    re-run the in-flight, holding or venue checks at all."""
    holdings = FakeSymbolHoldingsPort(
        holdings=[HeldAllocation(strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("9"))]
    )
    in_flight_work = FakeInFlightWorkPort(result=True)
    guard, holdings, in_flight_work, venue = _guard(
        holdings=holdings, in_flight_work=in_flight_work
    )

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
    assert venue.calls == []


async def test_in_flight_within_the_age_bound_raises_holding_not_settled_yet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard, holdings, _, venue = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

    with pytest.raises(HoldingNotSettledYet):
        await guard.check(
            pool=POOL,
            strategy_id=uuid4(),
            symbol="ETHUSDT",
            own_reservation_id=None,
            received_at=NOW - timedelta(seconds=30),
        )

    assert holdings.calls == []
    assert venue.calls == []


async def test_in_flight_past_the_age_bound_abandons_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = uuid4()
    guard, holdings, _, venue = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

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
    assert venue.calls == []


async def test_a_flat_strategy_proceeds() -> None:
    strategy_id = uuid4()
    other_strategy_holding = HeldAllocation(
        strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("0.7")
    )
    guard, holdings, in_flight_work, venue = _guard(
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
    assert venue.calls == []


async def test_only_the_strategys_own_net_decides_divergence() -> None:
    """A different strategy's non-zero holding on the same symbol must not
    refuse THIS strategy's open -- per strategy, not per pool. Also proves
    the venue is never read for a strategy that is itself flat."""
    strategy_id = uuid4()
    other_holding = HeldAllocation(
        strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("5")
    )
    guard, _, _, venue = _guard(
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
    assert venue.calls == []


# ---- S4: the divergent branch now classifies before refusing ----
#
# design.md § S4's own worked example: single strategy, L_S = L_P = 0.5.
# REAL when the venue agrees with the WHOLE POOL (0.5); GHOST when it agrees
# with the pool WITHOUT this strategy's own leg (0, since there is no other
# strategy here); AMBIGUOUS for anything else, including a failed read.


async def test_a_real_orphan_still_refuses_naming_the_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Owner decision A1: REAL is refused until S6 delivers closing it. The
    guard classifies it correctly here and now; only the ACTION on it is
    deferred."""
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _, venue = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
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
    assert "REAL" in outcome.refused
    assert venue.calls == [(POOL, "ETHUSDT")]
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_a_ghost_orphan_refuses_with_a_warning_naming_the_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The venue agrees with what the pool would net WITHOUT this strategy's
    leg (0, single strategy) -- a manual close or a liquidation this
    strategy's own position never rehearsed."""
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _, venue = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0")),
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
    assert "GHOST" in outcome.refused
    assert str(strategy_id) in outcome.refused
    assert "ETHUSDT" in outcome.refused
    assert str(allocation_id) in outcome.refused
    assert "0.5" in outcome.refused
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_an_ambiguous_orphan_refuses_naming_the_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A partial liquidation: the venue matches neither the whole pool nor
    the pool without this strategy's leg (design.md's own worked example)."""
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _, venue = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.3")),
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
    assert "AMBIGUOUS" in outcome.refused
    assert str(strategy_id) in outcome.refused
    assert str(allocation_id) in outcome.refused
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_a_failed_venue_read_classifies_as_ambiguous() -> None:
    """``VenueNetPositionPort`` never raises -- ``None`` is how it spells a
    failed or timed-out read, and the guard must still refuse cleanly."""
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _, venue = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=None),
    )

    outcome = await guard.check(
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.proceed is False
    assert outcome.refused is not None
    assert "AMBIGUOUS" in outcome.refused
