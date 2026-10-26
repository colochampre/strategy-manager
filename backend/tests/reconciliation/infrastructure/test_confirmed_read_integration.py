"""The two read-only adapters behind ``GET /reconciliation/confirmed`` on real
PostgreSQL (cd.1.30 / cd.1.31; design.md PR 15 addendum § G; note N8):
``StrategyNameAdapter`` and ``SqlAlchemyBookingProposalRepository.approved_since``.
Each answers a whole set in ONE statement.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.application.ports import (
    NewBookingProposal,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.strategy_name_adapter import (
    StrategyNameAdapter,
)
from tests.owner import OWNER_ID
from tests.reconciliation.infrastructure.conftest import (
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=30)


class _Statements:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self.sql: list[str] = []

    def _record(self, conn: object, cursor: object, statement: str, *args: object) -> None:
        self.sql.append(statement)

    def __enter__(self) -> "_Statements":
        event.listen(self._engine.sync_engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine.sync_engine, "before_cursor_execute", self._record)


async def _allocation(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    strategy_id, signal_id, allocation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
    )
    return strategy_id, allocation_id


async def test_names_come_back_by_allocation_in_one_statement(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    first = await _allocation(pg_session_factory)
    second = await _allocation(pg_session_factory)
    unknown = uuid4()

    async with pg_session_factory() as session:
        with _Statements(pg_engine) as statements:
            answer = await StrategyNameAdapter(session).strategies_for(
                [first[1], second[1], unknown]
            )

    assert set(answer) == {first[1], second[1]}
    assert answer[first[1]].strategy_id == first[0]
    assert answer[first[1]].name == f"strategy-{first[0]}"
    assert answer[second[1]].name == f"strategy-{second[0]}"
    assert len(statements.sql) == 1


async def test_no_allocation_asks_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    async with pg_session_factory() as session:
        with _Statements(pg_engine) as statements:
            answer = await StrategyNameAdapter(session).strategies_for([])

    assert answer == {}
    assert statements.sql == []


async def _discrepancy(
    factory: async_sessionmaker[AsyncSession], symbol: str, resolved: bool = False
) -> UUID:
    scan_id = uuid4()
    async with factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            symbol,
            Observation(DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE, Decimal("0"), Decimal("0.5")),
            [uuid4()],
            consecutive_scans=2,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=scan_id,
            at=NOW,
        )
        await session.commit()
        discrepancy_id = next(
            r.id for r in await repo.list_discrepancies(open_only=True) if r.symbol == symbol
        )
        if resolved:
            await repo.resolve_absent(OWNER_ID, POOL, [symbol], scan_id, NOW)
            await session.commit()
    return discrepancy_id


async def _proposal(
    factory: async_sessionmaker[AsyncSession],
    *,
    discrepancy_id: UUID,
    strategy_id: UUID,
    allocation_id: UUID,
    state: str,
    decided_at: datetime,
    fills: int = 2,
) -> UUID:
    fill = ProposedFillSnapshot(
        exchange_fill_id="f",
        exchange_order_id="o",
        side="SELL",
        quantity=Decimal("0.5"),
        price=Decimal("142.37"),
        fee=Decimal("0.03913"),
        fee_currency="USDT",
        filled_at=NOW,
    )
    async with factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        record = await repo.insert(
            NewBookingProposal(
                user_id=OWNER_ID,
                discrepancy_id=discrepancy_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol="STXUSDT.P",
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                side="SELL",
                quantity=Decimal("0.5"),
                observed_venue_net_base=Decimal("0"),
                observed_ledger_net_base=Decimal("0.5"),
                observed_allocation_ids=[allocation_id],
                fills=[fill] * fills,
                client_order_id=f"vnu:bybit:{uuid4()}",
                expires_at=NOW + timedelta(hours=24),
                prepared_by_job_id=uuid4(),
            )
        )
        assert record is not None
        if state != "PENDING":
            assert await repo.mark_state(
                OWNER_ID, record.id, state, decided_at, decided_by="system:auto-booking",
                decision_reason="reason",
            )
        await session.commit()
    return record.id


async def test_approved_since_keeps_the_window_and_the_open_discrepancies_and_nothing_else(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE booking_proposals"))
        await session.commit()
    strategy_id, allocation_id = await _allocation(pg_session_factory)

    async def approved(symbol: str, decided_at: datetime, resolved: bool) -> UUID:
        discrepancy_id = await _discrepancy(pg_session_factory, symbol, resolved)
        return await _proposal(
            pg_session_factory,
            discrepancy_id=discrepancy_id,
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            state="APPROVED",
            decided_at=decided_at,
        )

    recent_settled = await approved("AAAUSDT", NOW - timedelta(days=2), resolved=True)
    old_but_open = await approved("BBBUSDT", NOW - timedelta(days=90), resolved=False)
    await approved("CCCUSDT", NOW - timedelta(days=31), resolved=True)
    for state in ("PENDING", "REJECTED", "EXPIRED", "SUPERSEDED"):
        await _proposal(
            pg_session_factory,
            discrepancy_id=await _discrepancy(pg_session_factory, f"E{state}USDT"),
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            state=state,
            decided_at=NOW,
        )

    async with pg_session_factory() as session:
        with _Statements(pg_engine) as statements:
            answer = await SqlAlchemyBookingProposalRepository(session).approved_since(SINCE)

    assert {p.proposal_id for p in answer} == {recent_settled, old_but_open}
    assert len(statements.sql) == 1
    by_id = {p.proposal_id: p for p in answer}
    assert by_id[recent_settled].discrepancy_open is False
    assert by_id[old_but_open].discrepancy_open is True
    assert by_id[recent_settled].fill_count == 2
    assert by_id[recent_settled].decided_by == "system:auto-booking"
    assert by_id[recent_settled].allocation_id == allocation_id
    assert by_id[recent_settled].strategy_id == strategy_id
    assert by_id[recent_settled].quantity == Decimal("0.5")
    assert by_id[recent_settled].decided_at == NOW - timedelta(days=2)
