"""``ArchiveStrategy`` against real PostgreSQL (design.md § 8, "Archived
strategies: refusal, archive preconditions and the race"; owner decision
14; tasks.md 2c.1-2c.7).

Wires the REAL ``StrategyExposureAdapter`` and the REAL ``PoolLockAdapter``
-- not fakes -- mirroring ``tests/signals/application
/test_open_after_close_integration.py``'s own "_integration" convention:
the whole point of these tests is that the exposure query and the lock key
derivation are genuinely correct against a real schema, not merely that
``ArchiveStrategy``'s own branching is correct in isolation.

**Binding requirement 3 (refuse in the application, not through the
database).** ``StillEnabled``/``OpenPosition`` are raised BEFORE
``repository.update()`` is ever called, so this suite never needs (and
never exercises) the database's own ``archived_at IS NULL OR enabled =
false`` CHECK -- ``test_archiving_enabled_strategy_refused_409_still_enabled``
asserts the raised type is exactly ``StillEnabled``, never
``IntegrityError``.

**Binding requirement 5 (exposure multiplicity).**
``test_two_allocations_same_symbol_one_closed_one_open_archive_refuses``
seeds TWO allocations on the SAME market -- one fully round-tripped to a
net of zero, one still open -- and asserts archive still refuses. A buggy
adapter that computed one net PER SYMBOL (summing across allocations
instead of grouping by allocation first, the trap
``symbol_holdings``'s own docstring warns about) would still catch this
particular case by coincidence; what this test actually pins is that the
CLOSED allocation's id is absent from ``OpenPosition.exposure.allocations``
while the OPEN one's is present -- proving the check is genuinely
per-allocation, not merely "the pool is not flat".
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey as AllocationPoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.strategies.application.archive_strategy import (
    ArchiveStrategy,
    OpenPosition,
    StillEnabled,
)
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository

pytestmark = pytest.mark.integration

POOL = ("pionex", "spot", "USDT")
FIXED_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW


async def _seed_strategy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    enabled: bool,
    name: str | None = None,
    archived_at: datetime | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=name or f"strategy-{strategy_id}",
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                enabled=enabled,
                fill_mode="PARTIAL",
                archived_at=archived_at,
            )
        )
        await session.commit()


async def _seed_signal(
    session_factory: async_sessionmaker[AsyncSession], *, signal_id: UUID, strategy_id: UUID
) -> None:
    """``reservations.signal_id`` has a real FK into ``signals`` (migration
    ``0004``) -- every reservation this file seeds needs one to reference,
    even though nothing here reads the row back."""
    async with session_factory() as session:
        session.add(
            SignalRow(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"k-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=Decimal("1"),
                symbol="SEED",
                signal_type=str(strategy_id),
            )
        )
        await session.commit()


async def _seed_open_fill(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    symbol: str,
    quantity: Decimal,
) -> UUID:
    """One reservation + one opening execution attempt + one BUY ledger
    row, all FILLED -- one allocation open on ``symbol`` at exactly
    ``quantity``. Returns the allocation (reservation) id."""
    allocation_id = uuid4()
    signal_id = uuid4()
    await _seed_signal(session_factory, signal_id=signal_id, strategy_id=strategy_id)
    async with session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(
            Reservation(
                id=allocation_id,
                strategy_id=strategy_id,
                signal_id=signal_id,
                pool_key=AllocationPoolKey(
                    exchange=Exchange(POOL[0]),
                    venue=Venue(POOL[1]),
                    settlement_currency=Currency(POOL[2]),
                ),
                amount=Decimal("100"),
                status=ReservationStatus.FILLED,
                expires_at=FIXED_NOW + timedelta(seconds=30),
            )
        )
        await session.commit()

    attempt_id = uuid4()
    async with session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=allocation_id,
                closes_allocation_id=None,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=None,
                quote_amount=Decimal("100"),
                leverage=None,
                status=ExecutionStatus.FILLED,
                origin=ExecutionOrigin.SYSTEM,
                client_order_id=f"open-{attempt_id}",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=POOL[2],
                notional=quantity,
                exchange_order_id=f"ord-{attempt_id}",
                exchange_fill_id=f"fill-{attempt_id}",
                filled_at=FIXED_NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()

    return allocation_id


async def _seed_open_short_fill(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    symbol: str,
    quantity: Decimal,
) -> UUID:
    """A SHORT allocation: a SELL-opened reservation with no matching BUY,
    netting to ``-quantity`` (``symbol_holdings``'s sign convention). Exists
    only to build an offsetting-nets scenario: an allocation net of
    ``+quantity`` and one of ``-quantity`` on the SAME market sum to ZERO,
    which is exactly the shape a per-SYMBOL-summed exposure check would
    misread as flat while BOTH allocations are still genuinely open."""
    allocation_id = uuid4()
    signal_id = uuid4()
    await _seed_signal(session_factory, signal_id=signal_id, strategy_id=strategy_id)
    async with session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(
            Reservation(
                id=allocation_id,
                strategy_id=strategy_id,
                signal_id=signal_id,
                pool_key=AllocationPoolKey(
                    exchange=Exchange(POOL[0]),
                    venue=Venue(POOL[1]),
                    settlement_currency=Currency(POOL[2]),
                ),
                amount=Decimal("100"),
                status=ReservationStatus.FILLED,
                expires_at=FIXED_NOW + timedelta(seconds=30),
            )
        )
        await session.commit()

    attempt_id = uuid4()
    async with session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=allocation_id,
                closes_allocation_id=None,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=quantity,
                quote_amount=None,
                leverage=None,
                status=ExecutionStatus.FILLED,
                origin=ExecutionOrigin.SYSTEM,
                client_order_id=f"open-short-{attempt_id}",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=POOL[2],
                notional=quantity,
                exchange_order_id=f"ord-{attempt_id}",
                exchange_fill_id=f"fill-{attempt_id}",
                filled_at=FIXED_NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()

    return allocation_id


async def _seed_close_fill(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    allocation_id: UUID,
    symbol: str,
    quantity: Decimal,
) -> None:
    """A closing execution attempt + a SELL ledger row against an already-
    open allocation -- nets it to zero when ``quantity`` matches the
    opening fill exactly."""
    attempt_id = uuid4()
    async with session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=None,
                closes_allocation_id=allocation_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=quantity,
                quote_amount=None,
                leverage=None,
                status=ExecutionStatus.FILLED,
                origin=ExecutionOrigin.SYSTEM,
                client_order_id=f"close-{attempt_id}",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=POOL[2],
                notional=quantity,
                exchange_order_id=f"ord-{attempt_id}",
                exchange_fill_id=f"fill-{attempt_id}",
                filled_at=FIXED_NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()


def _build_archive_strategy(
    session: AsyncSession,
) -> ArchiveStrategy:
    return ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        exposure=StrategyExposureAdapter(
            ledger=SqlAlchemyLedgerRepository(session),
            symbol_holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,
        clock=FixedClock(),
    )


# --------------------------------------------------------------------------
# 2c.1 -- the happy path
# --------------------------------------------------------------------------


async def test_archiving_disabled_flat_strategy_succeeds(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)

    async with pg_session_factory() as session:
        result = await _build_archive_strategy(session).archive(strategy_id)

    assert result.already_archived is False
    assert result.strategy.archived_at == FIXED_NOW

    async with pg_session_factory() as verify:
        row = await verify.get(StrategyRow, strategy_id)
        assert row is not None
        assert row.archived_at == FIXED_NOW


# --------------------------------------------------------------------------
# 2c.2 / binding 3 -- enabled refuses in the application, never as an
# IntegrityError
# --------------------------------------------------------------------------


async def test_archiving_enabled_strategy_refused_409_still_enabled(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=True)

    async with pg_session_factory() as session:
        with pytest.raises(StillEnabled) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    # Refused in the application: the exception type is exactly
    # StillEnabled, never an IntegrityError from the database's own CHECK
    # (binding requirement 3) -- proving this required no write attempt at
    # all, since only a write could ever reach that constraint.
    assert type(excinfo.value) is StillEnabled
    assert "still enabled" in str(excinfo.value)

    async with pg_session_factory() as verify:
        row = await verify.get(StrategyRow, strategy_id)
        assert row is not None
        assert row.archived_at is None  # untouched


# --------------------------------------------------------------------------
# 2c.3 -- an open position refuses and names it
# --------------------------------------------------------------------------


async def test_archiving_disabled_strategy_with_open_position_refused_409_names_symbols(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)
    allocation_id = await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", quantity=Decimal("2")
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    exposure = excinfo.value.exposure
    assert exposure.symbols == frozenset({"ETHUSDT"})
    assert exposure.allocations == (allocation_id,)
    assert "ETHUSDT" in str(excinfo.value)

    async with pg_session_factory() as verify:
        row = await verify.get(StrategyRow, strategy_id)
        assert row is not None
        assert row.archived_at is None


async def test_archiving_refuses_on_an_unlisted_delisted_pair_too(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Decision 15: the allowed-pairs list gates OPENING signals only, so a
    position can legitimately still be open on a symbol no longer on the
    list. Archive must still see it -- it enumerates every market the
    ledger has ever recorded a fill for, not the strategy's current
    ``allowed_pairs`` (``StrategyExposureAdapter``'s own docstring)."""
    strategy_id = uuid4()
    # allowed_pairs left at its default empty array: the position was
    # opened before the pair was pruned from the list.
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)
    await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="DELISTEDUSDT", quantity=Decimal("1")
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    assert "DELISTEDUSDT" in excinfo.value.exposure.symbols


# --------------------------------------------------------------------------
# 2c.4 -- dust: NOT_CLOSABLE keeps the ledger net non-zero, archive refuses
# --------------------------------------------------------------------------


async def test_dust_that_close_position_reports_not_closable_keeps_ledger_net_nonzero_archive_refuses(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A residual below the venue's minimum order size is exactly what
    ``ClosePosition`` reports as ``NOT_CLOSABLE`` (``close_position.py``) --
    no order is ever placed for it, so the ledger's net base for that
    allocation stays whatever tiny non-zero amount it already was. This
    test seeds that residual directly (a fill leaving 0.00000001 open) --
    ``ArchiveStrategy`` has no opinion on WHY a position could not be
    closed, only that the ledger still shows one open, and it must refuse
    exactly the same way it would for a large one."""
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)
    dust = Decimal("0.00000001")
    allocation_id = await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="BTCUSDT", quantity=dust
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    assert excinfo.value.exposure.allocations == (allocation_id,)


# --------------------------------------------------------------------------
# binding 5 -- exposure multiplicity: one closed allocation, one open, SAME
# symbol -- archive must still refuse, naming ONLY the open one
# --------------------------------------------------------------------------


async def test_two_allocations_same_symbol_one_closed_one_open_archive_refuses(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)

    closed_allocation_id = await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="SOLUSDT", quantity=Decimal("3")
    )
    await _seed_close_fill(
        pg_session_factory,
        strategy_id=strategy_id,
        allocation_id=closed_allocation_id,
        symbol="SOLUSDT",
        quantity=Decimal("3"),
    )
    open_allocation_id = await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="SOLUSDT", quantity=Decimal("1")
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    exposure = excinfo.value.exposure
    # Per allocation (the multiplicity lesson), never summed per symbol: the
    # CLOSED allocation is absent, the OPEN one is present -- proving the
    # check inspected both allocations individually rather than concluding
    # from one merged number for the symbol.
    assert exposure.allocations == (open_allocation_id,)
    assert closed_allocation_id not in exposure.allocations
    assert exposure.symbols == frozenset({"SOLUSDT"})


async def test_two_allocations_same_symbol_offsetting_nets_both_still_flagged_open(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The discriminating case the previous test cannot rule out on its own:
    a LONG allocation net +2 and a SHORT allocation net -2 on the SAME
    market sum to ZERO. A per-SYMBOL-summed exposure check would read that
    as flat and let archive through; the per-allocation check
    (``symbol_holdings``'s own ``HAVING net_base != 0``, grouped by
    allocation) must still see both individually and refuse, naming BOTH
    allocation ids. Verified as genuinely discriminating: mutating
    ``StrategyExposureAdapter`` to sum net per symbol instead of grouping by
    allocation makes this exact test fail (see the apply-progress report's
    RED evidence) while leaving every other test in this file green."""
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)

    long_allocation_id = await _seed_open_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="XRPUSDT", quantity=Decimal("2")
    )
    short_allocation_id = await _seed_open_short_fill(
        pg_session_factory, strategy_id=strategy_id, symbol="XRPUSDT", quantity=Decimal("2")
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    exposure = excinfo.value.exposure
    assert set(exposure.allocations) == {long_allocation_id, short_allocation_id}
    assert exposure.symbols == frozenset({"XRPUSDT"})


# --------------------------------------------------------------------------
# 2c.5 -- idempotent
# --------------------------------------------------------------------------


async def test_archive_is_idempotent_same_archived_at_on_second_call(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)

    async with pg_session_factory() as session:
        first = await _build_archive_strategy(session).archive(strategy_id)
    async with pg_session_factory() as session:
        second = await _build_archive_strategy(session).archive(strategy_id)

    assert first.already_archived is False
    assert second.already_archived is True
    assert first.strategy.archived_at == second.strategy.archived_at == FIXED_NOW


async def test_archive_unknown_strategy_raises() -> None:
    class _NeverCalledRepository:
        async def get_by_id(self, strategy_id: UUID) -> None:
            return None

        async def get_by_id_for_update(self, strategy_id: UUID) -> None:
            raise AssertionError(
                "the row lock must never be attempted once the unlocked "
                "existence read already found nothing"
            )

    use_case = ArchiveStrategy(
        repository=_NeverCalledRepository(),  # type: ignore[arg-type]
        pool_lock=None,  # type: ignore[arg-type]
        exposure=None,  # type: ignore[arg-type]
        commit=None,  # type: ignore[arg-type]
        clock=FixedClock(),
    )
    with pytest.raises(UnknownStrategy):
        await use_case.archive(uuid4())


# --------------------------------------------------------------------------
# 2c.6 / 2c.7 -- an archived strategy is read-only
# --------------------------------------------------------------------------


async def test_archived_strategy_patch_refused_409_strategy_archived(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(
        pg_session_factory, strategy_id=strategy_id, enabled=False, archived_at=FIXED_NOW
    )

    async with pg_session_factory() as session:
        use_case = UpdateStrategy(
            repository=SqlAlchemyStrategyRepository(session),
            commit=session,  # type: ignore[arg-type]
            enablement_log=SqlAlchemyEnablementLog(session),
            clock=FixedClock(),  # type: ignore[arg-type]
        )
        with pytest.raises(StrategyArchived):
            await use_case.update(UpdateCommand(strategy_id=strategy_id, name="renamed"))


async def test_archived_strategy_pairs_put_refused_409_strategy_archived(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(
        pg_session_factory, strategy_id=strategy_id, enabled=False, archived_at=FIXED_NOW
    )

    async with pg_session_factory() as session:
        use_case = ReplaceAllowedPairs(
            repository=SqlAlchemyStrategyRepository(session),
            commit=session,  # type: ignore[arg-type]
        )
        with pytest.raises(StrategyArchived):
            await use_case.replace(
                ReplaceAllowedPairsCommand(strategy_id=strategy_id, pairs=["ETHUSDT"])
            )


async def test_enabling_archived_strategy_refused_enabled_unchanged(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_strategy(
        pg_session_factory, strategy_id=strategy_id, enabled=False, archived_at=FIXED_NOW
    )

    async with pg_session_factory() as session:
        use_case = UpdateStrategy(
            repository=SqlAlchemyStrategyRepository(session),
            commit=session,  # type: ignore[arg-type]
            enablement_log=SqlAlchemyEnablementLog(session),
            clock=FixedClock(),  # type: ignore[arg-type]
        )
        with pytest.raises(StrategyArchived):
            await use_case.update(UpdateCommand(strategy_id=strategy_id, enabled=True))

    async with pg_session_factory() as verify:
        row = await verify.get(StrategyRow, strategy_id)
        assert row is not None
        assert row.enabled is False  # unchanged -- the PATCH never wrote anything

    async with pg_session_factory() as verify:
        events = await SqlAlchemyEnablementLog(verify).list_for(strategy_id)
        assert events == []  # no event either: the refusal wrote nothing at all


# --------------------------------------------------------------------------
# exposure adapter -- live reservations and in-flight attempts, no ledger
# fill yet (supplementary coverage for tasks.md 2c.12's remaining branches)
# --------------------------------------------------------------------------


async def test_live_reservation_with_no_fill_yet_still_refuses_archive(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A signal that reserved capital but has not yet produced a fill (or
    even an execution attempt) still holds capital -- ``live_reservations``
    catches it even though the ledger has nothing to say yet."""
    strategy_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)
    reservation_id = uuid4()
    signal_id = uuid4()
    await _seed_signal(pg_session_factory, signal_id=signal_id, strategy_id=strategy_id)
    async with pg_session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(
            Reservation(
                id=reservation_id,
                strategy_id=strategy_id,
                signal_id=signal_id,
                pool_key=AllocationPoolKey(
                    exchange=Exchange(POOL[0]),
                    venue=Venue(POOL[1]),
                    settlement_currency=Currency(POOL[2]),
                ),
                amount=Decimal("50"),
                status=ReservationStatus.PENDING,
                expires_at=FIXED_NOW + timedelta(seconds=30),
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as excinfo:
            await _build_archive_strategy(session).archive(strategy_id)

    assert excinfo.value.exposure.live_reservations == (reservation_id,)
    assert excinfo.value.exposure.symbols == frozenset()
