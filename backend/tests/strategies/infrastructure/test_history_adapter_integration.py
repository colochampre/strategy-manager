"""``StrategyHistoryAdapter`` against real PostgreSQL (design.md addendum 9x,
§ B and § C; tasks.md 9xb.2).

The counts are plain reads, so the ORM-built schema of this directory's
conftest is enough: no count depends on a foreign key or a trigger. (The
exhaustiveness guard, which does, runs on a ``head`` database in
``test_strategy_references_guard.py``.)

The tested strategy lives on ``bybit/usdt-m/USDT``. The tables that hang off a
reservation or a signal need a parent row; a parent that belongs to ANOTHER
strategy is used wherever a kind has to be counted on its own, so the expected
history of each case is exact.

Symbol spelling: the alert is spelled ``STXUSDT.P``, every row seeded on the
venue side is ``STXUSDT``, a proposal is ``STXUSDT_PERP`` and the strategy
allows ``STXUSDT``. Counting must not care.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.models import BookingProposalRow
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.ports import StrategyHistory
from strategy_manager.strategies.infrastructure.enablement_log import (
    SqlAlchemyEnablementLog,
    StrategyEnablementEventRow,
)
from strategy_manager.strategies.infrastructure.history_adapter import StrategyHistoryAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from tests.owner import OWNER_ID, ensure_delivery, ensure_pool, secret_hash

pytestmark = pytest.mark.integration

_POOL = ("bybit", "usdt-m", "USDT")
_OTHER_POOL = ("pionex", "spot", "USDT")

Factory = async_sessionmaker[AsyncSession]


def _history(**counts: int) -> StrategyHistory:
    base = {
        "signals": 0,
        "reservations": 0,
        "execution_attempts": 0,
        "ledger_entries": 0,
        "booking_proposals": 0,
        "enablement_events": 0,
        "subscriptions": 0,
    }
    base.update(counts)
    return StrategyHistory(**base)


async def _host_strategy(session: AsyncSession) -> UUID:
    """A strategy nobody counts, to host the subscription of a seeded delivery."""
    host = uuid4()
    exchange, venue, currency = _POOL
    await session.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode, author_id, "
            "webhook_secret_hash) "
            "VALUES (:id, :name, :exchange, :venue, :currency, false, 'PARTIAL', :author, "
            "'fixture')"
        ),
        {
            "id": host,
            "name": f"host-{host}",
            "exchange": exchange,
            "venue": venue,
            "currency": currency,
            "author": OWNER_ID,
        },
    )
    return host


async def _seed(factory: Factory, *rows: object) -> None:
    """Adds ``rows`` in one commit. A reservation or a booking proposal is placed
    in its user's pool on its market, seeded when missing (migration 0030), so
    ``_reservation`` and ``_proposal`` can stay plain constructors."""
    async with factory() as session:
        for row in rows:
            if isinstance(row, ReservationRow | BookingProposalRow):
                row.pool_id = await ensure_pool(
                    session,
                    (row.exchange, row.venue, row.settlement_currency),
                    user_id=row.user_id,
                )
                if isinstance(row, ReservationRow) and row.delivery_id is None:
                    # The reservation serves a delivery (migration 0032), whose
                    # subscription is hosted on a strategy of its own so that no
                    # count under test sees it.
                    row.delivery_id = await ensure_delivery(
                        session,
                        signal_id=row.signal_id,
                        strategy_id=row.strategy_id,
                        user_id=row.user_id,
                        subscription_strategy_id=await _host_strategy(session),
                    )
            if isinstance(row, SubscriptionRow):
                row.pool_id = await ensure_pool(session, _POOL, user_id=row.user_id)
        session.add_all(rows)
        await session.commit()


async def _strategy(factory: Factory) -> UUID:
    strategy_id = uuid4()
    exchange, venue, currency = _POOL
    await _seed(
        factory,
        StrategyRow(
            id=strategy_id,
            name=f"strategy-{strategy_id}",
            exchange=exchange,
            venue=venue,
            settlement_currency=currency,
            author_id=OWNER_ID,
            webhook_secret_hash=secret_hash("fixture-secret"),
            enabled=False,
            fill_mode="PARTIAL",
            allowed_pairs=["STXUSDT"],
        ),
    )
    return strategy_id


def _signal(strategy_id: UUID, *, status: str = "ACCEPTED", symbol: str = "STXUSDT.P") -> SignalRow:
    return SignalRow(
        id=uuid4(),
        strategy_id=strategy_id,
        idempotency_key=f"key-{uuid4()}",
        raw_payload={},
        status=status,
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("1"),
        symbol=symbol,
        signal_type=str(strategy_id),
    )


def _reservation(
    strategy_id: UUID,
    signal_id: UUID,
    *,
    pool: tuple[str, str, str] = _POOL,
    status: str = "PENDING",
) -> ReservationRow:
    exchange, venue, currency = pool
    return ReservationRow(
        id=uuid4(),
        user_id=OWNER_ID,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        amount=Decimal("10"),
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _attempt(
    *,
    reservation_id: UUID | None = None,
    closes_allocation_id: UUID | None = None,
    signal_id: UUID | None = None,
    status: str = "SUBMITTED",
) -> ExecutionAttemptRow:
    exchange, venue, currency = _POOL
    attempt_id = uuid4()
    return ExecutionAttemptRow(
        id=attempt_id,
        user_id=OWNER_ID,
        reservation_id=reservation_id,
        closes_allocation_id=closes_allocation_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol="STXUSDT",
        side="BUY",
        quantity=Decimal("1"),
        status=status,
        client_order_id=f"client-{attempt_id}",
    )


def _ledger_entry(strategy_id: UUID, allocation_id: UUID, attempt_id: UUID) -> LedgerEntryRow:
    exchange, venue, currency = _POOL
    entry_id = uuid4()
    return LedgerEntryRow(
        id=entry_id,
        user_id=OWNER_ID,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol="STXUSDT",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1"),
        fee=Decimal("0"),
        fee_currency=currency,
        notional=Decimal("1"),
        exchange_order_id=f"order-{entry_id}",
        exchange_fill_id=f"fill-{entry_id}",
        filled_at=datetime.now(UTC),
        usd_rate_at_fill=Decimal("1"),
    )


def _proposal(strategy_id: UUID, *, state: str = "PENDING") -> BookingProposalRow:
    exchange, venue, currency = _POOL
    return BookingProposalRow(
        id=uuid4(),
        user_id=OWNER_ID,
        discrepancy_id=uuid4(),
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol="STXUSDT_PERP",
        kind="ATTRIBUTABLE_SINGLE_ALLOCATION",
        allocation_id=uuid4(),
        strategy_id=strategy_id,
        side="BUY",
        quantity=Decimal("1"),
        observed_venue_net_base=Decimal("1"),
        observed_ledger_net_base=Decimal("0"),
        observed_allocation_ids=[],
        fills=[],
        client_order_id=f"proposal-{uuid4()}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        prepared_by_job_id=uuid4(),
        state=state,
    )


def _event(strategy_id: UUID) -> StrategyEnablementEventRow:
    return StrategyEnablementEventRow(
        id=uuid4(),
        strategy_id=strategy_id,
        enabled=True,
        occurred_at=datetime.now(UTC),
        origin="OBSERVED",
    )


def _subscription(strategy_id: UUID, *, status: str = "ACTIVE") -> SubscriptionRow:
    """``pool_id`` is placed by ``_seed``, in the owner's pool on ``_POOL``."""
    return SubscriptionRow(
        id=uuid4(),
        user_id=OWNER_ID,
        strategy_id=strategy_id,
        pool_id=0,
        allocation_percent=Decimal("20"),
        status=status,
    )


def _adapter(session: AsyncSession) -> StrategyHistoryAdapter:
    return StrategyHistoryAdapter(
        session=session,
        signals=SqlAlchemySignalRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        ledger=SqlAlchemyLedgerRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        enablement_log=SqlAlchemyEnablementLog(session),
    )


async def _history_of(factory: Factory, strategy_id: UUID) -> StrategyHistory:
    async with factory() as session:
        return await _adapter(session).history(strategy_id)


async def _seed_signal_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    await _seed(factory, _signal(strategy_id))


async def _seed_reservation_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    carrier = _signal(other)
    await _seed(factory, carrier)
    await _seed(factory, _reservation(strategy_id, carrier.id))


async def _seed_attempt_through_its_reservation(
    factory: Factory, strategy_id: UUID, other: UUID
) -> None:
    carrier = _signal(other)
    await _seed(factory, carrier)
    reservation = _reservation(strategy_id, carrier.id)
    await _seed(factory, reservation)
    await _seed(factory, _attempt(reservation_id=reservation.id))


async def _seed_ledger_entry_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    carrier = _signal(other)
    await _seed(factory, carrier)
    reservation = _reservation(other, carrier.id)
    await _seed(factory, reservation)
    attempt = _attempt(reservation_id=reservation.id)
    await _seed(factory, attempt)
    await _seed(factory, _ledger_entry(strategy_id, reservation.id, attempt.id))


async def _seed_proposal_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    await _seed(factory, _proposal(strategy_id))


async def _seed_event_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    await _seed(factory, _event(strategy_id))


async def _seed_subscription_only(factory: Factory, strategy_id: UUID, other: UUID) -> None:
    await _seed(factory, _subscription(strategy_id))


async def test_a_strategy_with_nothing_counts_zero_in_every_kind(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    await _seed_ledger_entry_only(pg_session_factory, other, other)

    history = await _history_of(pg_session_factory, strategy_id)

    assert history == _history()
    assert history.is_empty() is True


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        pytest.param(_seed_signal_only, _history(signals=1), id="signals"),
        pytest.param(_seed_reservation_only, _history(reservations=1), id="reservations"),
        pytest.param(
            _seed_attempt_through_its_reservation,
            _history(reservations=1, execution_attempts=1),
            id="execution_attempts",
        ),
        pytest.param(_seed_ledger_entry_only, _history(ledger_entries=1), id="ledger_entries"),
        pytest.param(_seed_proposal_only, _history(booking_proposals=1), id="booking_proposals"),
        pytest.param(_seed_event_only, _history(enablement_events=1), id="enablement_events"),
        pytest.param(_seed_subscription_only, _history(subscriptions=1), id="subscriptions"),
    ],
)
async def test_one_row_of_each_kind_is_counted_in_its_own_kind(
    pg_session_factory: Factory,
    seed: Callable[[Factory, UUID, UUID], Awaitable[None]],
    expected: StrategyHistory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    await seed(pg_session_factory, strategy_id, other)

    history = await _history_of(pg_session_factory, strategy_id)

    assert history == expected
    # Migrations 0028 and 0031: an enablement event and a subscription are
    # counted, and are the kinds that do not make the history non-empty.
    assert history.is_empty() is (seed in (_seed_event_only, _seed_subscription_only))


async def test_subscriptions_are_counted_in_every_status(pg_session_factory: Factory) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _seed(
        pg_session_factory,
        _subscription(strategy_id, status="ENDED"),
        _subscription(strategy_id, status="ENDED"),
        _subscription(strategy_id, status="LEAVING"),
    )

    history = await _history_of(pg_session_factory, strategy_id)

    assert history == _history(subscriptions=3)


async def test_an_execution_attempt_is_counted_through_its_reservation_its_closed_allocation_and_its_signal(  # noqa: E501
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    # The reservation and the signal that carry the attempts belong to the
    # strategy under test, but a second reservation and signal belong to the
    # other one, so each route is proven on its own below.
    mine = _signal(strategy_id)
    carrier = _signal(other)
    theirs = _signal(other)
    await _seed(pg_session_factory, mine, carrier, theirs)
    reservation = _reservation(strategy_id, carrier.id)
    their_reservation = _reservation(other, theirs.id)
    await _seed(pg_session_factory, reservation, their_reservation)
    await _seed(
        pg_session_factory,
        _attempt(reservation_id=reservation.id),
        _attempt(closes_allocation_id=reservation.id, status="FILLED"),
        _attempt(reservation_id=their_reservation.id, signal_id=mine.id),
    )

    history = await _history_of(pg_session_factory, strategy_id)

    assert history.execution_attempts == 3


@pytest.mark.parametrize(
    "route",
    ["reservation", "closed_allocation", "signal"],
)
async def test_each_route_to_a_strategy_counts_an_attempt_on_its_own(
    pg_session_factory: Factory, route: str
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    mine = _signal(strategy_id)
    carrier = _signal(other)
    theirs = _signal(other)
    await _seed(pg_session_factory, mine, carrier, theirs)
    reservation = _reservation(strategy_id, carrier.id)
    their_reservation = _reservation(other, theirs.id)
    await _seed(pg_session_factory, reservation, their_reservation)
    attempts = {
        "reservation": _attempt(reservation_id=reservation.id),
        "closed_allocation": _attempt(closes_allocation_id=reservation.id),
        "signal": _attempt(reservation_id=their_reservation.id, signal_id=mine.id),
    }
    await _seed(pg_session_factory, attempts[route])

    history = await _history_of(pg_session_factory, strategy_id)

    assert history.execution_attempts == 1


async def test_terminal_rows_count_too(pg_session_factory: Factory) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    rejected = _signal(strategy_id, status="REJECTED")
    carrier = _signal(other)
    await _seed(pg_session_factory, rejected, carrier)
    released = _reservation(strategy_id, carrier.id, status="RELEASED")
    await _seed(pg_session_factory, released)
    await _seed(
        pg_session_factory,
        _attempt(reservation_id=released.id, status="FAILED"),
        _proposal(strategy_id, state="REJECTED"),
    )

    history = await _history_of(pg_session_factory, strategy_id)

    assert history == _history(
        signals=1, reservations=1, execution_attempts=1, booking_proposals=1
    )


async def test_another_strategys_rows_are_never_counted(pg_session_factory: Factory) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    signal = _signal(other)
    await _seed(pg_session_factory, signal)
    reservation = _reservation(other, signal.id)
    await _seed(pg_session_factory, reservation)
    attempt = _attempt(reservation_id=reservation.id, signal_id=signal.id)
    await _seed(pg_session_factory, attempt)
    await _seed(
        pg_session_factory,
        _ledger_entry(other, reservation.id, attempt.id),
        _proposal(other),
        _event(other),
        _subscription(other),
    )

    mine = await _history_of(pg_session_factory, strategy_id)
    theirs = await _history_of(pg_session_factory, other)

    assert mine == _history()
    assert theirs == _history(
        signals=1,
        reservations=1,
        execution_attempts=1,
        ledger_entries=1,
        booking_proposals=1,
        enablement_events=1,
        subscriptions=1,
    )


async def test_a_reservation_in_another_pool_is_counted(pg_session_factory: Factory) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    carrier = _signal(other)
    await _seed(pg_session_factory, carrier)
    stray = _reservation(strategy_id, carrier.id, pool=_OTHER_POOL)
    await _seed(pg_session_factory, stray)

    history = await _history_of(pg_session_factory, strategy_id)

    assert (stray.exchange, stray.venue, stray.settlement_currency) == _OTHER_POOL
    assert history.reservations == 1


async def test_a_signal_spelled_as_tradingview_spells_it_counts_for_a_strategy_allowing_the_market_key(  # noqa: E501
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    signal = _signal(strategy_id, symbol="STXUSDT.P")
    carrier = _signal(other, symbol="STXUSDT.P")
    await _seed(pg_session_factory, signal, carrier)
    reservation = _reservation(strategy_id, carrier.id)
    await _seed(pg_session_factory, reservation)
    attempt = _attempt(reservation_id=reservation.id)
    await _seed(pg_session_factory, attempt)
    await _seed(
        pg_session_factory,
        _ledger_entry(strategy_id, reservation.id, attempt.id),
        _proposal(strategy_id),
    )

    history = await _history_of(pg_session_factory, strategy_id)

    assert (signal.symbol, attempt.symbol, "STXUSDT") == ("STXUSDT.P", "STXUSDT", "STXUSDT")
    assert history == _history(
        signals=1,
        reservations=1,
        execution_attempts=1,
        ledger_entries=1,
        booking_proposals=1,
    )
