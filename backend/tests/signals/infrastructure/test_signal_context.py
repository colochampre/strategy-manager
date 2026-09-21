"""Unit tests: ``SignalContextAdapter`` populates ``SignalContext.
own_reservation_id`` and ``received_at`` (design.md § S2 "the query";
tasks.md's S2b: "SignalContext.own_reservation_id"). ``HoldingGuard``'s
"own reservation -> resume" branch depends on the first; its age-bounded
abandonment depends on the second.

Fakes only -- no database. ``ReservationRepositoryPort.find_by_signal_id``
already exists (slice 4); this only asserts ``SignalContextAdapter`` calls it
with the CURRENT signal's own id, not the prior signal's, and carries the
result through.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal
from strategy_manager.signals.infrastructure.signal_context import SignalContextAdapter
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy

RECEIVED_AT = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


@dataclass
class FakeSignalRepository:
    by_id: dict[UUID, WebhookSignal]

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None:
        return self.by_id.get(signal_id)

    async def find_prior(self, strategy_id: UUID, symbol: str, before: datetime) -> None:
        return None


@dataclass
class FakeStrategyRepository:
    strategy: Strategy

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        return self.strategy

    async def insert(self, strategy: Strategy) -> None:
        raise NotImplementedError

    async def list_all(self) -> list[Strategy]:
        raise NotImplementedError

    async def update(self, strategy: Strategy) -> None:
        raise NotImplementedError


@dataclass
class FakeReservationRepository:
    by_signal_id: dict[UUID, Reservation]

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        return self.by_signal_id.get(signal_id)


def _signal(signal_id: UUID, strategy_id: UUID) -> WebhookSignal:
    return WebhookSignal(
        id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=IdempotencyKey(f"k-{signal_id}"),
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("50000"),
        symbol="BTCUSDT",
        signal_type=str(strategy_id),
        raw_payload={},
        received_at=RECEIVED_AT,
        status=SignalStatus.ACCEPTED,
    )


def _strategy(strategy_id: UUID) -> Strategy:
    return Strategy(
        id=strategy_id,
        name="s",
        policy=AllocationPolicy(
            exchange=Exchange.BYBIT,
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            fill_mode=FillMode.PARTIAL,
        ),
        enabled=True,
    )


def _reservation(reservation_id: UUID, strategy_id: UUID, signal_id: UUID) -> Reservation:
    from strategy_manager.allocation.domain.pool_key import PoolKey

    return Reservation(
        id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        pool_key=PoolKey(
            exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT
        ),
        amount=Decimal("100"),
        status=ReservationStatus.PENDING,
        expires_at=RECEIVED_AT,
    )


async def test_own_reservation_id_is_none_when_no_reservation_exists_for_this_signal() -> None:
    strategy_id, signal_id = uuid4(), uuid4()
    adapter = SignalContextAdapter(
        signals=FakeSignalRepository({signal_id: _signal(signal_id, strategy_id)}),
        strategies=FakeStrategyRepository(_strategy(strategy_id)),
        reservations=FakeReservationRepository({}),
    )

    context = await adapter.load(signal_id)

    assert context.own_reservation_id is None
    assert context.received_at == RECEIVED_AT


async def test_own_reservation_id_is_populated_when_this_signal_already_has_one() -> None:
    """A retried ``signal.process`` job whose earlier attempt already
    created a reservation for THIS signal -- the guard's "resume" case."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    reservation = _reservation(reservation_id, strategy_id, signal_id)
    adapter = SignalContextAdapter(
        signals=FakeSignalRepository({signal_id: _signal(signal_id, strategy_id)}),
        strategies=FakeStrategyRepository(_strategy(strategy_id)),
        reservations=FakeReservationRepository({signal_id: reservation}),
    )

    context = await adapter.load(signal_id)

    assert context.own_reservation_id == reservation_id
