"""``GET /reconciliation/confirmed`` -- the infrastructure half of T8 (spec
"Confirmed Discrepancy Read Endpoint" and "The Confirmed Discrepancies Route
Is An Admin Route Under /api"; design.md PR 15 addendum § G; notes N3 and N8;
requirement R17).

Real PostgreSQL behind the real router: what the route serves is what the
database holds, in three statements, and the call writes nothing.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.identity.infrastructure.dependencies import UNAUTHORIZED_DETAIL
from strategy_manager.main import create_app
from strategy_manager.reconciliation.application.auto_book_pending import AUTO_BOOKING_ACTOR
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
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import ADMIN_HEADERS, sign_in_as_admin
from tests.owner import OWNER_EMAIL, OWNER_ID, ensure_pool, seed_other_user
from tests.reconciliation.infrastructure.conftest import (
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL = ("bybit", "usdt-m", "USDT")

_TOP_KEYS = {
    "read_at",
    "dry_run",
    "needs_owner_count",
    "needs_owner",
    "being_booked",
    "booked",
}
_DISCREPANCY_KEYS = {
    "discrepancy_id",
    "exchange",
    "venue",
    "settlement_currency",
    "symbol",
    "kind",
    "reason",
    "venue_net_base",
    "ledger_net_base",
    "allocations",
    "confirmed_at",
    "last_observed_at",
    # B.8 / AD10: whose discrepancy it is, beside it.
    "user_email",
}
_BOOKING_KEYS = {
    "proposal_id",
    "discrepancy_id",
    "exchange",
    "venue",
    "settlement_currency",
    "symbol",
    "kind",
    "strategy_id",
    "strategy_name",
    "allocation_id",
    "side",
    "quantity",
    "fill_count",
    "decided_at",
    "decided_by",
    "execution_attempt_id",
    "discrepancy_open",
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "dry_run", False)
    monkeypatch.setattr(get_settings(), "reconciliation_auto_booking_grace_seconds", 300)
    yield


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE booking_proposals"))
        await session.commit()

    app = FastAPI()
    app.include_router(reconciliation_router)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _discrepancy(
    factory: async_sessionmaker[AsyncSession],
    *,
    symbol: str,
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    allocations: Sequence[UUID] | None = None,
    confirmed_ago: timedelta = timedelta(hours=1),
    venue_net_base: Decimal = Decimal("0"),
    ledger_net_base: Decimal = Decimal("0.5"),
    user_id: UUID = OWNER_ID,
) -> UUID:
    async with factory() as session:
        await SqlAlchemyDiscrepancyRepository(session).upsert_open(
            user_id,
            POOL,
            symbol,
            Observation(kind, venue_net_base, ledger_net_base),
            list(allocations) if allocations is not None else [uuid4()],
            consecutive_scans=2,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=uuid4(),
            at=datetime.now(UTC) - confirmed_ago,
        )
        await session.commit()
    async with factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            open_only=True
        )
    return next(r.id for r in records if r.symbol == symbol and r.user_id == user_id)


async def _strategy_and_allocation(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
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


async def _approved_proposal(
    factory: async_sessionmaker[AsyncSession],
    *,
    discrepancy_id: UUID,
    strategy_id: UUID,
    allocation_id: UUID,
    symbol: str,
    decided_by: str = AUTO_BOOKING_ACTOR,
    observed: tuple[Decimal, Decimal] = (Decimal("0"), Decimal("0.5")),
) -> UUID:
    fill = ProposedFillSnapshot(
        exchange_fill_id=f"f-{uuid4()}",
        exchange_order_id="5001",
        side="SELL",
        quantity=Decimal("0.5"),
        price=Decimal("142.37"),
        fee=Decimal("0.03913"),
        fee_currency="USDT",
        filled_at=datetime.now(UTC),
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
                symbol=symbol,
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                side="SELL",
                quantity=Decimal("0.5"),
                observed_venue_net_base=observed[0],
                observed_ledger_net_base=observed[1],
                observed_allocation_ids=[allocation_id],
                fills=[fill, fill],
                client_order_id=f"vnu:bybit:{uuid4()}",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                prepared_by_job_id=uuid4(),
            )
        )
        assert record is not None
        assert await repo.mark_state(
            OWNER_ID, record.id, "APPROVED", datetime.now(UTC), decided_by=decided_by
        )
        await session.commit()
    return record.id


async def test_without_an_assertion_the_route_answers_401(client: AsyncClient) -> None:
    response = await client.get("/reconciliation/confirmed")

    assert response.status_code == 401
    assert response.json() == {"detail": UNAUTHORIZED_DETAIL}


async def test_the_route_is_mounted_under_api_and_has_no_unprefixed_twin() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        assert (await api.get("/api/reconciliation/confirmed")).status_code == 401
        unprefixed = await api.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)
        assert unprefixed.status_code == 404


async def test_the_body_has_the_keys_and_shape_of_the_design(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    factory = pg_session_factory
    strategy_id, allocation_id = await _strategy_and_allocation(factory)
    needs = await _discrepancy(
        factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )
    being = await _discrepancy(
        factory,
        symbol="BBBUSDT",
        allocations=[allocation_id],
        confirmed_ago=timedelta(seconds=10),
    )
    booked_discrepancy = await _discrepancy(factory, symbol="CCCUSDT")
    proposal_id = await _approved_proposal(
        factory,
        discrepancy_id=booked_discrepancy,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="CCCUSDT",
    )

    response = await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert set(body) == _TOP_KEYS
    assert body["dry_run"] is False
    assert body["needs_owner_count"] == len(body["needs_owner"]) == 1
    [need] = body["needs_owner"]
    assert set(need) == _DISCREPANCY_KEYS
    assert need["discrepancy_id"] == str(needs)
    assert need["reason"] == "NOT_BOOKABLE"
    [wait] = body["being_booked"]
    assert set(wait) == _DISCREPANCY_KEYS
    assert wait["discrepancy_id"] == str(being)
    assert wait["reason"] is None
    [allocation] = wait["allocations"]
    assert allocation == {
        "allocation_id": str(allocation_id),
        "strategy_id": str(strategy_id),
        "strategy_name": f"strategy-{strategy_id}",
    }
    [booking] = body["booked"]
    assert set(booking) == _BOOKING_KEYS
    assert booking["proposal_id"] == str(proposal_id)
    assert booking["decided_by"] == "automatic"
    assert booking["fill_count"] == 2
    assert booking["discrepancy_open"] is True
    assert booking["strategy_name"] == f"strategy-{strategy_id}"
    assert booking["execution_attempt_id"] is None


async def test_money_and_quantities_are_strings(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    await _discrepancy(
        pg_session_factory,
        symbol="DDDUSDT",
        kind=DiscrepancyKind.NO_MATCHING_ALLOCATION,
        venue_net_base=Decimal("0.123456789"),
        ledger_net_base=Decimal("0.5"),
    )
    booked = await _discrepancy(pg_session_factory, symbol="EEEUSDT")
    await _approved_proposal(
        pg_session_factory,
        discrepancy_id=booked,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="EEEUSDT",
    )

    body = (await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)).json()

    assert len(body["needs_owner"]) == 1
    assert len(body["booked"]) == 1
    [need] = body["needs_owner"]
    assert isinstance(need["venue_net_base"], str)
    assert isinstance(need["ledger_net_base"], str)
    assert Decimal(need["venue_net_base"]) == Decimal("0.123456789")
    assert Decimal(need["ledger_net_base"]) == Decimal("0.5")
    [booking] = body["booked"]
    assert isinstance(booking["quantity"], str)
    assert Decimal(booking["quantity"]) == Decimal("0.5")


async def test_quantities_read_back_at_scale_18_are_written_in_plain_notation(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """``Numeric(38, 18)`` reads a zero back as ``Decimal("0E-18")``, whose
    ``str`` is ``"0E-18"``: a full close (venue net 0) must not reach the wire so."""
    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    await _discrepancy(
        pg_session_factory,
        symbol="FFFUSDT",
        kind=DiscrepancyKind.NO_MATCHING_ALLOCATION,
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("0"),
    )
    booked = await _discrepancy(pg_session_factory, symbol="GGGUSDT")
    await _approved_proposal(
        pg_session_factory,
        discrepancy_id=booked,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="GGGUSDT",
    )

    body = (await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)).json()

    [need] = body["needs_owner"]
    [booking] = body["booked"]
    for text_value in (need["venue_net_base"], need["ledger_net_base"], booking["quantity"]):
        assert "E" not in text_value
    assert need["venue_net_base"] == "0.000000000000000000"
    assert need["ledger_net_base"] == "0.000000000000000000"
    assert booking["quantity"] == "0.500000000000000000"


@pytest.mark.parametrize("dry_run", [True, False])
async def test_dry_run_is_the_setting_and_the_lists_are_what_the_database_holds(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", dry_run)
    await _discrepancy(
        pg_session_factory, symbol="FFFUSDT", kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE
    )

    body = (await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)).json()

    assert body["dry_run"] is dry_run
    assert body["needs_owner_count"] == 1


async def test_a_resolved_or_observed_discrepancy_is_in_no_list(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with pg_session_factory() as session:
        await SqlAlchemyDiscrepancyRepository(session).upsert_open(
            OWNER_ID,
            POOL,
            "GGGUSDT",
            Observation(DiscrepancyKind.NO_MATCHING_ALLOCATION, Decimal("1"), Decimal("0")),
            [uuid4()],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=datetime.now(UTC),
        )
        await session.commit()

    body = (await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)).json()

    assert (body["needs_owner"], body["being_booked"], body["booked"]) == ([], [], [])
    assert body["needs_owner_count"] == 0


async def _count_statements(
    client: AsyncClient, engine: AsyncEngine
) -> tuple[int, dict[str, Any]]:
    statements: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        response = await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)
    assert response.status_code == 200
    return len(statements), response.json()


async def test_the_statement_count_is_the_same_for_one_and_for_twenty_open_discrepancies(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
) -> None:
    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    first = await _discrepancy(pg_session_factory, symbol="HHH0USDT", allocations=[allocation_id])
    await _approved_proposal(
        pg_session_factory,
        discrepancy_id=first,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="HHH0USDT",
    )
    one, body_one = await _count_statements(client, pg_engine)

    for i in range(1, 20):
        await _discrepancy(
            pg_session_factory,
            symbol=f"HHH{i}USDT",
            kind=DiscrepancyKind.NO_MATCHING_ALLOCATION,
            allocations=[allocation_id, uuid4()],
        )
    twenty, body_twenty = await _count_statements(client, pg_engine)

    assert len(body_one["booked"]) == 1
    assert len(body_twenty["needs_owner"]) == 19
    # The fourth is the users' e-mails (B.8), one query for every item.
    assert one == twenty == 4


_TABLES = text(
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
)


async def _snapshot(factory: async_sessionmaker[AsyncSession]) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    async with factory() as session:
        for (table,) in (await session.execute(_TABLES)).all():
            row = (
                await session.execute(
                    text(
                        "SELECT count(*), "
                        "coalesce(md5(string_agg(t::text, ',' ORDER BY t::text)), '') "
                        f'FROM "{table}" t'
                    )
                )
            ).one()
            snapshot[table] = (row[0], row[1])
    return snapshot


async def test_the_snapshot_notices_a_change_so_the_next_test_is_not_vacuous(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await _snapshot(pg_session_factory)

    await _discrepancy(pg_session_factory, symbol="LLLUSDT")

    assert await _snapshot(pg_session_factory) != before


async def test_the_call_changes_no_table(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    booked = await _discrepancy(pg_session_factory, symbol="IIIUSDT", allocations=[allocation_id])
    await _approved_proposal(
        pg_session_factory,
        discrepancy_id=booked,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="IIIUSDT",
    )
    await _discrepancy(
        pg_session_factory, symbol="JJJUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )
    before = await _snapshot(pg_session_factory)

    response = await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert await _snapshot(pg_session_factory) == before


async def test_each_confirmed_discrepancy_names_the_e_mail_of_its_user(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B.8 / B.10 (AD10): the panel reads this route, so it is here that the
    admin learns whose discrepancy each one is. Two users hold one on the SAME
    market and symbol; each item names its own user's e-mail."""
    async with pg_session_factory() as session:
        other_id = await seed_other_user(session)
        await ensure_pool(session, POOL, user_id=other_id)
        other_email = (
            await session.execute(
                text("SELECT email FROM users WHERE id = :id"), {"id": other_id}
            )
        ).scalar_one()
        await session.commit()
    mine = await _discrepancy(pg_session_factory, symbol="MMMUSDT")
    theirs = await _discrepancy(pg_session_factory, symbol="MMMUSDT", user_id=other_id)

    response = await client.get("/reconciliation/confirmed", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    emails = {
        item["discrepancy_id"]: item.get("user_email") for item in response.json()["needs_owner"]
    }
    assert emails == {str(mine): OWNER_EMAIL, str(theirs): other_email}


async def test_the_discrepancies_route_answers_as_before(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """R17: the new route leaves ``GET /reconciliation/discrepancies`` alone."""

    await _discrepancy(pg_session_factory, symbol="KKKUSDT")

    response = await client.get("/reconciliation/discrepancies", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    [row] = response.json()
    assert set(row) == {
        "id",
        "exchange",
        "venue",
        "settlement_currency",
        "symbol",
        "kind",
        "venue_net_base",
        "ledger_net_base",
        "open_allocation_ids",
        "consecutive_scans",
        "status",
        "first_observed_at",
        "last_observed_at",
        "confirmed_at",
        "resolved_at",
        # B.8: whose row it is, beside the row.
        "user_email",
    }
    assert row["symbol"] == "KKKUSDT"
