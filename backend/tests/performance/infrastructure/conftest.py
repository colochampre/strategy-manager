"""Real-PostgreSQL fixtures for the fills-source tests. They are the ledger
tests' own (``strategies``, ``signals``, ``reservations``,
``execution_attempts`` and ``ledger_entries`` from ``create_all``, plus the
seeded pools), re-exported rather than copied so the two cannot drift.

``operations_ledger`` is the one ledger every integration test of a strategy's
operations reads (design addendum "a strategy's operations", section H).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

# --- the one ledger of unit 9p.4 (design addendum "a strategy's operations",
# section H) ---------------------------------------------------------------------
#
# One strategy, ``S1``, in the pool ``bybit/usdt-m/USDT`` that allows ``STXUSDT``,
# and a second strategy, ``S2``, in the same pool. Every fill is written through
# ``RecordFill`` (the production write path), never by the simulated exchange: a
# fill "at the alert's price" is a fill whose price the fixture chose.
#
# Spellings: the real operations open as ``STXUSDT.P`` (TradingView's) and close
# as ``STXUSDT`` (the venue's); the rehearsal operations open as ``STXUSDT_PERP``
# (Pionex's) and close as ``STXUSDT.P``. No assertion may compare two spellings
# as text: every one reads pair ``STXUSDT`` and base currency ``STX``.

OPERATIONS_T0 = datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=UTC)
# The alert price of the "small quantity" rehearsal operation: 18 places, so a
# quantity of 0.000007 makes the stored notional round and the derived average
# differ from the fill's own price in its last places.
SMALL_ALERT_PRICE = "0.451234567890123456"
SMALL_QUANTITY = "0.000007"


@dataclass(frozen=True, slots=True)
class RealOperations:
    """The real half of the ledger: what exists before any rehearsal row."""

    strategy_id: UUID
    other_strategy_id: UUID
    real_long: UUID
    real_short: UUID
    open_real: UUID
    mixed: UUID
    mixed_attempt: UUID
    other: UUID


@dataclass(frozen=True, slots=True)
class OperationsLedger:
    """Every id of the one ledger. ``closed_at`` is the instant of each closed
    operation's last fill, in the order the list must serve them."""

    strategy_id: UUID
    other_strategy_id: UUID
    real_long: UUID
    real_short: UUID
    open_real: UUID
    open_rehearsal: UUID
    mixed: UUID
    fixed_one: UUID
    alert_small: UUID
    alert_of_one: UUID
    opened_at_one_closed_at_alert: UUID
    other: UUID

    @property
    def real_closed(self) -> tuple[UUID, ...]:
        """S1's closed real operations, newest first (the mixed one lists as a
        real operation, from its real fills)."""
        return (self.mixed, self.real_short, self.real_long)

    @property
    def rehearsal_closed(self) -> tuple[UUID, ...]:
        """S1's closed rehearsal operations, newest first."""
        return (
            self.opened_at_one_closed_at_alert,
            self.alert_of_one,
            self.alert_small,
            self.fixed_one,
        )


def _at(hours: int, minutes: int = 0) -> datetime:
    return OPERATIONS_T0 + timedelta(hours=hours, minutes=minutes)


def _rehearsal_id() -> str:
    return f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}"


async def _set_alert_price(
    factory: async_sessionmaker[AsyncSession], allocation_id: UUID, price: str
) -> None:
    """``signals.price`` of the signal the reservation names: the price the alert
    carried, and the one a fill "at the alert's price" has."""
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE signals SET price = :price WHERE id = "
                "(SELECT signal_id FROM reservations WHERE id = :id)"
            ),
            {"price": Decimal(price), "id": allocation_id},
        )
        await session.commit()


async def build_real_operations(factory: async_sessionmaker[AsyncSession]) -> RealOperations:
    """The real operations of ``S1`` and ``S2``, with no rehearsal row at all.

    A real LONG with three opening fills of different sizes and prices, a real
    SHORT, an open real position, the real half of a mixed allocation, and one
    closed operation of ``S2``. ``add_rehearsal_operations`` adds the rest."""
    from tests.performance.infrastructure.test_allocation_fills_source import (
        _fill,
        _record,
        _seed_allocation,
    )

    strategy_id, real_long, long_attempt = await _seed_allocation(factory)
    other_strategy_id, other, other_attempt = await _seed_allocation(factory)
    _, real_short, short_attempt = await _seed_allocation(factory, strategy_id=strategy_id)
    _, open_real, open_attempt = await _seed_allocation(factory, strategy_id=strategy_id)
    _, mixed, mixed_attempt = await _seed_allocation(factory, strategy_id=strategy_id)

    async with factory() as session:
        await session.execute(
            text("UPDATE strategies SET allowed_pairs = ARRAY['STXUSDT']::text[]")
        )
        await session.commit()

    def fill(allocation: UUID, attempt: UUID, owner: UUID, side: str, **kwargs: Any) -> FillRecord:
        return _fill(
            strategy_id=owner, allocation_id=allocation, attempt_id=attempt, side=side, **kwargs
        )

    await _record(
        factory,
        # The real LONG: three opening fills (100 @ 0.40, 300 @ 0.44, 600 @ 0.46),
        # sold as 1000 @ 0.50.
        fill(real_long, long_attempt, strategy_id, "BUY", quantity="100", price="0.40",
             symbol="STXUSDT.P", fee="0.1", filled_at=_at(0)),
        fill(real_long, long_attempt, strategy_id, "BUY", quantity="300", price="0.44",
             symbol="STXUSDT.P", fee="0.1", filled_at=_at(0, 1)),
        fill(real_long, long_attempt, strategy_id, "BUY", quantity="600", price="0.46",
             symbol="STXUSDT.P", fee="0.1", filled_at=_at(0, 2)),
        fill(real_long, long_attempt, strategy_id, "SELL", quantity="1000", price="0.50",
             symbol="STXUSDT", fee="0.1", filled_at=_at(1)),
        # The real SHORT: sold 200 @ 0.50, bought back 200 @ 0.45.
        fill(real_short, short_attempt, strategy_id, "SELL", quantity="200", price="0.50",
             symbol="STXUSDT.P", fee="0.05", filled_at=_at(2)),
        fill(real_short, short_attempt, strategy_id, "BUY", quantity="200", price="0.45",
             symbol="STXUSDT", fee="0.05", filled_at=_at(3)),
        # An open real position: one side only.
        fill(open_real, open_attempt, strategy_id, "BUY", quantity="100", price="0.45",
             symbol="STXUSDT.P", filled_at=_at(4)),
        # The real half of the mixed allocation: a full real round trip.
        fill(mixed, mixed_attempt, strategy_id, "BUY", quantity="50", price="0.40",
             symbol="STXUSDT.P", filled_at=_at(5)),
        fill(mixed, mixed_attempt, strategy_id, "SELL", quantity="50", price="0.41",
             symbol="STXUSDT", filled_at=_at(5, 30)),
        # S2's one closed operation, in the same pool.
        fill(other, other_attempt, other_strategy_id, "BUY", quantity="10", price="0.50",
             symbol="STXUSDT.P", filled_at=_at(11)),
        fill(other, other_attempt, other_strategy_id, "SELL", quantity="10", price="0.51",
             symbol="STXUSDT", filled_at=_at(11, 30)),
    )
    return RealOperations(
        strategy_id=strategy_id,
        other_strategy_id=other_strategy_id,
        real_long=real_long,
        real_short=real_short,
        open_real=open_real,
        mixed=mixed,
        mixed_attempt=mixed_attempt,
        other=other,
    )


async def add_rehearsal_operations(
    factory: async_sessionmaker[AsyncSession], real: RealOperations
) -> OperationsLedger:
    """The rehearsal half: an open rehearsal position, the rehearsal half of the
    mixed allocation, and four rehearsal round trips whose signals carry an alert
    price. Rehearsal operations open as ``STXUSDT_PERP`` and close as
    ``STXUSDT.P``; their fill ids carry the rehearsal prefix."""
    from tests.performance.infrastructure.test_allocation_fills_source import (
        _fill,
        _record,
        _seed_allocation,
    )

    strategy_id = real.strategy_id
    seeded: dict[str, tuple[UUID, UUID]] = {}
    for name in (
        "open_rehearsal",
        "fixed_one",
        "alert_small",
        "alert_of_one",
        "opened_at_one_closed_at_alert",
    ):
        _, allocation, attempt = await _seed_allocation(factory, strategy_id=strategy_id)
        seeded[name] = (allocation, attempt)

    def rehearsal_fill(
        allocation: UUID, attempt: UUID, side: str, quantity: str, price: str, **kwargs: object
    ) -> object:
        return _fill(
            strategy_id=strategy_id,
            allocation_id=allocation,
            attempt_id=attempt,
            side=side,
            quantity=quantity,
            price=price,
            fill_id=_rehearsal_id(),
            **kwargs,
        )

    fixed, fixed_attempt = seeded["fixed_one"]
    small, small_attempt = seeded["alert_small"]
    one, one_attempt = seeded["alert_of_one"]
    late, late_attempt = seeded["opened_at_one_closed_at_alert"]
    pending, pending_attempt = seeded["open_rehearsal"]
    for allocation, alert in (
        (pending, "0.4512"),
        (fixed, "0.4512"),
        (small, SMALL_ALERT_PRICE),
        (one, "1"),
        (late, "0.4512"),
    ):
        await _set_alert_price(factory, allocation, alert)

    await _record(
        factory,
        # An open rehearsal position.
        rehearsal_fill(pending, pending_attempt, "BUY", "100", "1",
                       symbol="STXUSDT_PERP", filled_at=_at(4)),
        # The rehearsal half of the mixed allocation: a full rehearsal round trip.
        rehearsal_fill(real.mixed, real.mixed_attempt, "BUY", "50", "1",
                       symbol="STXUSDT_PERP", filled_at=_at(6)),
        rehearsal_fill(real.mixed, real.mixed_attempt, "SELL", "50", "1",
                       symbol="STXUSDT.P", filled_at=_at(6, 30)),
        # Filled at 1 against an alert of 0.4512: FIXED_ONE.
        rehearsal_fill(fixed, fixed_attempt, "BUY", "1250", "1",
                       symbol="STXUSDT_PERP", filled_at=_at(7)),
        rehearsal_fill(fixed, fixed_attempt, "SELL", "1250", "1",
                       symbol="STXUSDT.P", filled_at=_at(7, 30)),
        # Filled at its alert's price, with a quantity small enough that the derived
        # average differs from the fill in its last places: ALERT.
        rehearsal_fill(small, small_attempt, "BUY", SMALL_QUANTITY, SMALL_ALERT_PRICE,
                       symbol="STXUSDT_PERP", filled_at=_at(8)),
        rehearsal_fill(small, small_attempt, "SELL", SMALL_QUANTITY, SMALL_ALERT_PRICE,
                       symbol="STXUSDT.P", filled_at=_at(8, 30)),
        # Filled at 1 against an alert of exactly 1: ALERT.
        rehearsal_fill(one, one_attempt, "BUY", "10", "1",
                       symbol="STXUSDT_PERP", filled_at=_at(9)),
        rehearsal_fill(one, one_attempt, "SELL", "10", "1",
                       symbol="STXUSDT.P", filled_at=_at(9, 30)),
        # Opened at 1 and closed at its alert's price, the position that was open
        # when decision 45 landed: FIXED_ONE.
        rehearsal_fill(late, late_attempt, "BUY", "100", "1",
                       symbol="STXUSDT_PERP", filled_at=_at(10)),
        rehearsal_fill(late, late_attempt, "SELL", "100", "0.4512",
                       symbol="STXUSDT.P", filled_at=_at(10, 30)),
    )
    return OperationsLedger(
        strategy_id=strategy_id,
        other_strategy_id=real.other_strategy_id,
        real_long=real.real_long,
        real_short=real.real_short,
        open_real=real.open_real,
        open_rehearsal=pending,
        mixed=real.mixed,
        fixed_one=fixed,
        alert_small=small,
        alert_of_one=one,
        opened_at_one_closed_at_alert=late,
        other=real.other,
    )


@pytest.fixture
async def operations_ledger(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> OperationsLedger:
    """The one ledger of unit 9p.4, in the ORM schema of this package."""
    real = await build_real_operations(pg_session_factory)
    return await add_rehearsal_operations(pg_session_factory, real)
