"""The scenarios of admin-api "One Request Reads One Database State And Writes
Nothing" that T6 and T7 do not cover (design addendum "open positions", sections
G and L; tasks.md op.1.28) [DB].

(a) while another transaction holds a pool's advisory lock, the route answers;
(b) a settle that writes fills and the attempt's status completes while the route
    is held mid-read, and the route raises no serialization error;
(c) a read writes no row;
(d) the route answers with ``DRY_RUN`` true and false, with no credential in the
    vault.

(e), that the Alembic head is the one ``main`` has, is a command and not a test
(tasks.md op.1.28 (e)).

Real PostgreSQL. The held reads use the harness of rule R13: events the test
controls, and ``not task.done()`` where an actor must be shown to wait or not to
wait, never a ``sleep``.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import ADMIN_HEADERS, act_as, sign_in_as_admin
from tests.owner import OWNER_ID
from tests.performance.fakes import HeldOpenStateSource
from tests.performance.infrastructure.guard_cases import seed_guard_cases
from tests.performance.infrastructure.test_open_positions_snapshot import (
    WAIT,
    _fill_the_order,
    _held_app,
    _read_held_across,
    _seed_order_in_flight,
)

pytestmark = pytest.mark.integration

URL ="/api/positions/open"
TABLES = (
    "ledger_entries",
    "reservations",
    "execution_attempts",
    "reconciliation_discrepancies",
    "booking_proposals",
    "strategies",
    "signals",
    "capital_pools",
    "exchange_credentials",
)


def _app(factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    return act_as(app, OWNER_ID)


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


async def _get(app: FastAPI) -> Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(URL, headers=ADMIN_HEADERS)


async def test_the_route_answers_while_another_transaction_holds_a_pools_advisory_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The route takes no lock a writer waits on and waits on none: the holder of
    the pool's lock keeps it open for the whole request."""
    await seed_guard_cases(pg_session_factory)
    holder = pg_session_factory()
    try:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey("bybit", "usdt-m", "USDT", OWNER_ID))
        await PgAdvisoryLockAdapter(holder).acquire(LockKey("pionex", "spot", "USDT", OWNER_ID))

        request = asyncio.create_task(_get(_app(pg_session_factory)))
        response = await asyncio.wait_for(request, WAIT)

        assert request.done()
        assert response.status_code == 200, response.text
        assert response.json()["positions"], "the seed holds open positions"
    finally:
        await holder.rollback()
        await holder.close()


async def test_a_settle_is_not_delayed_by_a_held_route_and_the_route_has_no_serialization_error(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_order_in_flight(pg_session_factory)
    held_slot: list[HeldOpenStateSource] = []
    settled = asyncio.Event()

    async def _settle() -> None:
        # The writer must finish BY ITSELF while the read is parked: if the route
        # held anything a writer waits for, this would time out.
        await asyncio.wait_for(_fill_the_order(pg_session_factory, *ids), WAIT)
        settled.set()

    body = await _read_held_across(
        _held_app(pg_session_factory, held_slot), held_slot, _settle
    )

    assert settled.is_set(), "the settle did not complete while the route was held"
    # A read-only REPEATABLE READ transaction cannot fail on a concurrent write:
    # the route answered (the helper asserts 200) and it answered the state before.
    assert [o["attempt_id"] for o in body["orders"]] == [str(ids[2])]
    assert body["positions"] == []


async def _checksums(factory: async_sessionmaker[AsyncSession]) -> dict[str, tuple[int, str]]:
    """Row count and an md5 of every row's text, per table: an UPDATE is seen as
    well as an INSERT or a DELETE."""
    out: dict[str, tuple[int, str]] = {}
    async with factory() as session:
        for table in TABLES:
            row = (
                await session.execute(
                    text(
                        f"SELECT count(*), md5(coalesce(string_agg(t::text, ',' "  # noqa: S608
                        f"ORDER BY t::text), '')) FROM {table} t"
                    )
                )
            ).one()
            out[table] = (int(row[0]), str(row[1]))
    return out


async def test_a_read_writes_no_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_guard_cases(pg_session_factory)
    before = await _checksums(pg_session_factory)

    response = await _get(_app(pg_session_factory))

    assert response.status_code == 200, response.text
    assert await _checksums(pg_session_factory) == before
    assert before["ledger_entries"][0] > 0 and before["execution_attempts"][0] > 0


@pytest.mark.parametrize("dry_run", [True, False])
async def test_the_route_answers_in_both_modes_with_no_credential_in_the_vault(
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", dry_run)
    await seed_guard_cases(pg_session_factory)
    async with pg_session_factory() as session:
        vault = (await session.execute(text("SELECT count(*) FROM exchange_credentials"))).scalar()
    assert vault == 0, "this test is about a vault with no credential in it"

    response = await _get(_app(pg_session_factory))

    assert response.status_code == 200, response.text
    text_body = response.text.lower()
    for forbidden in ("api_key", "api_secret", "secret", "password", "postgresql"):
        assert forbidden not in text_body, f"{forbidden!r} is in the body"
