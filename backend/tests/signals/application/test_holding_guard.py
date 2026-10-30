"""Unit tests: ``HoldingGuard``'s precedence order (spec: capital-allocation
§ Existing-Position Guard; design.md § "Guard order"):

own reservation -> resume (skip entirely) -> in flight (defer by seeding a
continuation, or abandon past the age bound) -> flat -> proceed -> divergent
-> classify (S4) -> refuse.

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

from strategy_manager.shared.domain.mode import Mode
from strategy_manager.signals.application.holding_guard import GuardOutcome, HoldingGuard
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.holding import HeldAllocation
from tests.allocation.fakes import RecordedModes

POOL: PoolKey = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
MAX_AGE_SECONDS = 600.0
# The strategy's author, in whose pool the signal is worked.
AUTHOR = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0e")


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class FakeSymbolHoldingsPort:
    holdings: list[HeldAllocation] = field(default_factory=list)
    calls: list[tuple[PoolKey, str]] = field(default_factory=list)
    # Whose holdings each call asked about (multi-user design AD8).
    users: list[UUID] = field(default_factory=list)

    async def symbol_holdings(
        self, user_id: UUID, pool: PoolKey, symbol: str
    ) -> list[HeldAllocation]:
        self.users.append(user_id)
        self.calls.append((pool, symbol))
        return self.holdings


@dataclass
class FakeInFlightWorkPort:
    result: bool = False
    closing_allocations: list[UUID] = field(default_factory=list)
    calls: list[tuple[PoolKey, UUID, str, datetime]] = field(default_factory=list)
    closing_allocation_calls: list[tuple[PoolKey, UUID, str]] = field(default_factory=list)
    # Whose in-flight work each call asked about (multi-user design AD8).
    users: list[UUID] = field(default_factory=list)

    async def in_flight(
        self, user_id: UUID, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool:
        self.users.append(user_id)
        self.calls.append((pool, strategy_id, symbol, now))
        return self.result

    async def submitted_closing_allocations(
        self, user_id: UUID, pool: PoolKey, strategy_id: UUID, symbol: str
    ) -> list[UUID]:
        self.users.append(user_id)
        self.closing_allocation_calls.append((pool, strategy_id, symbol))
        return self.closing_allocations


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
    allocation_modes: RecordedModes | None = None,
    simulated_venue: FakeVenueNetPositionPort | None = None,
) -> tuple[HoldingGuard, FakeSymbolHoldingsPort, FakeInFlightWorkPort, FakeVenueNetPositionPort]:
    """The venue returned is the live one. A test about both modes passes
    ``simulated_venue``; without it, both modes read the same fake."""
    holdings_port = holdings or FakeSymbolHoldingsPort()
    in_flight_port = in_flight_work or FakeInFlightWorkPort()
    venue_port = venue_net_position or FakeVenueNetPositionPort()
    guard = HoldingGuard(
        holdings=holdings_port,
        in_flight_work=in_flight_port,
        venue_net_position={Mode.LIVE: venue_port, Mode.SIMULATION: simulated_venue or venue_port},
        allocation_modes=allocation_modes or RecordedModes(),
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
        user_id=AUTHOR,
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


async def test_the_in_flight_read_asks_about_the_authors_work() -> None:
    """Multi-user design AD8 (B.5): the in-flight read is the strategy
    author's, whose pool the signal is worked in."""
    guard, _, in_flight_work, _ = _guard()

    await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=uuid4(),
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert in_flight_work.users == [AUTHOR]


async def test_in_flight_within_the_age_bound_defers_by_seeding_a_continuation() -> None:
    """design.md § S5, amending S2: the in-flight branch no longer raises
    into the queue's failure backoff. It defers instead, naming which
    allocation's closing attempt (if any) the caller should await."""
    strategy_id = uuid4()
    allocation_id = uuid4()
    in_flight_work = FakeInFlightWorkPort(result=True, closing_allocations=[allocation_id])
    guard, holdings, _, venue = _guard(in_flight_work=in_flight_work)

    outcome = await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW - timedelta(seconds=30),
    )

    assert outcome.proceed is False
    assert outcome.refused is None
    assert outcome.awaited_allocation_ids == [allocation_id]
    assert in_flight_work.closing_allocation_calls == [(POOL, strategy_id, "ETHUSDT")]
    # Both reads of the deferral (is it in flight, which close to await) ask as
    # the strategy's author (multi-user design AD8).
    assert in_flight_work.users == [AUTHOR, AUTHOR]
    assert holdings.calls == []
    assert venue.calls == []


async def test_in_flight_within_the_age_bound_with_no_closing_attempt_defers_empty() -> None:
    """The in-flight condition can also be a SUBMITTED opening attempt or a
    PENDING reservation -- neither is a close to await, so
    ``awaited_allocation_ids`` comes back empty and the continuation
    re-checks the whole guard from scratch on its own cadence instead."""
    guard, holdings, _, venue = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

    outcome = await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=uuid4(),
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW - timedelta(seconds=30),
    )

    assert outcome.proceed is False
    assert outcome.refused is None
    assert outcome.awaited_allocation_ids == []
    assert holdings.calls == []
    assert venue.calls == []


async def test_in_flight_past_the_age_bound_abandons_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = uuid4()
    guard, holdings, _, venue = _guard(in_flight_work=FakeInFlightWorkPort(result=True))

    with caplog.at_level("WARNING"):
        outcome = await guard.check(
            user_id=AUTHOR,
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
        user_id=AUTHOR,
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
    assert holdings.users == [AUTHOR]  # the strategy author's holdings, nobody else's
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
        user_id=AUTHOR,
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


async def _check(guard: HoldingGuard, strategy_id: UUID) -> GuardOutcome:
    return await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )


@pytest.mark.parametrize("mode", list(Mode))
async def test_a_holding_is_compared_with_the_venue_of_the_mode_it_opened_in(mode: Mode) -> None:
    """Decision 26: a user can go live holding a simulated position, and decision 14
    leaves a real one open under the brake. Compared with the other side's venue
    either reads flat there, which is a GHOST: an alert and a refusal for a position
    that is fine."""
    strategy_id = uuid4()
    holding = HeldAllocation(strategy_id, uuid4(), Decimal("0.5"))
    holds_it = FakeVenueNetPositionPort(net=Decimal("0.5"))
    flat = FakeVenueNetPositionPort(net=Decimal("0"))
    live, simulated = (holds_it, flat) if mode is Mode.LIVE else (flat, holds_it)
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[holding]),
        venue_net_position=live,
        simulated_venue=simulated,
        allocation_modes=RecordedModes(mode),
    )

    outcome = await _check(guard, strategy_id)

    assert outcome.refused is None
    assert outcome.real_orphan_holdings == [holding]
    assert holds_it.calls == [(POOL, "ETHUSDT")]
    assert flat.calls == []


async def test_another_modes_holding_does_not_count_towards_the_pools_net() -> None:
    """The other strategy's simulated leg is on no real venue, so with it counted
    the live venue would not match the pool's net and the REAL orphan would read
    AMBIGUOUS."""
    strategy_id = uuid4()
    real = HeldAllocation(strategy_id, uuid4(), Decimal("0.5"))
    simulated = HeldAllocation(uuid4(), uuid4(), Decimal("0.2"))
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[real, simulated]),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
        allocation_modes=RecordedModes(by_allocation={simulated.allocation_id: Mode.SIMULATION}),
    )

    outcome = await _check(guard, strategy_id)

    assert outcome.real_orphan_holdings == [real]


async def test_a_long_in_one_mode_and_a_short_in_the_other_do_not_cancel_out() -> None:
    """They are two positions on two venues, and netting them would call the
    strategy flat and open a third."""
    strategy_id = uuid4()
    real = HeldAllocation(strategy_id, uuid4(), Decimal("0.5"))
    simulated = HeldAllocation(strategy_id, uuid4(), Decimal("-0.5"))
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[real, simulated]),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
        simulated_venue=FakeVenueNetPositionPort(net=Decimal("-0.5")),
        allocation_modes=RecordedModes(by_allocation={simulated.allocation_id: Mode.SIMULATION}),
    )

    outcome = await _check(guard, strategy_id)

    assert outcome.proceed is False
    assert outcome.real_orphan_holdings == [real, simulated]


async def test_a_refusal_in_one_mode_closes_nothing_in_the_other() -> None:
    """A REAL orphan is closed so the opening can follow, and a refusal means it
    never will, so nothing is closed for it."""
    strategy_id = uuid4()
    real = HeldAllocation(strategy_id, uuid4(), Decimal("0.5"))
    ghost = HeldAllocation(strategy_id, uuid4(), Decimal("0.3"))
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[real, ghost]),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
        simulated_venue=FakeVenueNetPositionPort(net=Decimal("0")),
        allocation_modes=RecordedModes(by_allocation={ghost.allocation_id: Mode.SIMULATION}),
    )

    outcome = await _check(guard, strategy_id)

    assert outcome.reason == "DIVERGENT_HOLDING_GHOST"
    assert outcome.real_orphan_holdings is None


async def test_a_flat_market_asks_no_mode() -> None:
    modes = RecordedModes()
    guard, _, _, _ = _guard(allocation_modes=modes)

    outcome = await _check(guard, uuid4())

    assert outcome.proceed is True
    assert modes.asked == []


async def test_the_modes_read_are_the_users_own() -> None:
    strategy_id = uuid4()
    holding = HeldAllocation(strategy_id, uuid4(), Decimal("0.5"))
    modes = RecordedModes()
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[holding]),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
        allocation_modes=modes,
    )

    await _check(guard, strategy_id)

    assert modes.asked == [(AUTHOR, holding.allocation_id)]


async def test_a_real_orphan_is_reported_for_the_caller_to_close_not_refused() -> None:
    """design.md § S6, owner decision 3: REAL is never refused. The guard
    classifies it correctly here and now and reports the strategy's own
    holdings via ``real_orphan_holdings`` -- the caller (``CloseOrphans``)
    is the one that actually closes it and defers the open."""
    strategy_id, allocation_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    guard, _, _, venue = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.5")),
    )

    outcome = await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.proceed is False
    assert outcome.refused is None
    assert outcome.real_orphan_holdings == [own_holding]
    assert venue.calls == [(POOL, "ETHUSDT")]


async def test_a_real_orphan_reports_only_the_calling_strategys_own_holdings() -> None:
    """A second strategy sharing the same market must never be closed by
    the first strategy's own REAL classification (design.md § S4's own
    worked example: S +0.5, T +0.2, both legs still open -> REAL)."""
    strategy_id, other_strategy_id = uuid4(), uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    other_holding = HeldAllocation(
        strategy_id=other_strategy_id, allocation_id=uuid4(), net_base=Decimal("0.2")
    )
    guard, _, _, _ = _guard(
        holdings=FakeSymbolHoldingsPort(holdings=[own_holding, other_holding]),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=FakeVenueNetPositionPort(net=Decimal("0.7")),
    )

    outcome = await guard.check(
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.real_orphan_holdings == [own_holding]


async def test_a_ghost_orphan_refuses_with_an_error_naming_the_details(
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
            user_id=AUTHOR,
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
    # ERROR, not WARNING: ERROR reaches the owner's Telegram through the alert
    # bridge, and a GHOST is a position the venue no longer holds (cd.f6).
    assert [r.levelname for r in caplog.records if "ghost" in r.getMessage()] == ["ERROR"]


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
            user_id=AUTHOR,
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
    assert not any(record.levelname == "ERROR" for record in caplog.records)


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
        user_id=AUTHOR,
        pool=POOL,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        own_reservation_id=None,
        received_at=NOW,
    )

    assert outcome.proceed is False
    assert outcome.refused is not None
    assert "AMBIGUOUS" in outcome.refused
