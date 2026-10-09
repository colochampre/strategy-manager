"""API tests for ``GET /api/strategies/{id}/share-preview`` (design.md, unit 12f
addendum, sections C2, C3, H and J; spec: admin-api "The Share Preview Route Serves
The Amount A Share Asks For"; tasks.md 12f.9.12).

The route answers what a share of the strategy's OWN pool's TOTAL balance would ask
for: the amount of one share asked about (``exact``) and of every whole share
(``steps``), each computed by the allocation's own sizing function from one read of
the balance. It is read-only by construction: no lock, no write, no exchange, no
vault.

Mounted through ``create_app()`` so the ``/api`` prefix and the application's
redacted 422 handler are part of what is proven, with ``get_session`` overridden to a
real PostgreSQL session (the ORM schema of ``tests/ledger/infrastructure/conftest.py``:
every assertion reads rows by their keys and no constraint decides an outcome). No
exchange is reached from this suite and no credential is needed.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.allocation.application.ports import PoolSizing
from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.decision import SkipReason, decide
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.percent import requested_from_percent
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.strategies.infrastructure.router import get_pool_sizing
from tests.accounts.infrastructure.test_pools_router import _snapshot
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.performance.infrastructure.test_performance_router import _walk

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"
_WAIT = 5.0  # seconds; only ever a ceiling for a hung test, never a pacing delay

BYBIT = ("bybit", "usdt-m", "USDT")
BINANCE = ("binance", "usdt-m", "USDT")
BYBIT_KEY = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)

Factory = async_sessionmaker[AsyncSession]


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


def _app(factory: Factory) -> FastAPI:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    return app


@pytest.fixture
async def client(pg_session_factory: Factory) -> AsyncIterator[AsyncClient]:  # noqa: F811
    async with AsyncClient(
        transport=ASGITransport(app=_app(pg_session_factory)), base_url="http://test"
    ) as api:
        yield api


async def _add_pool(factory: Factory, pool: tuple[str, str, str], minimum: str) -> None:
    exchange, venue, currency = pool
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES (:e, :v, :c, :minimum)"
            ),
            {"e": exchange, "v": venue, "c": currency, "minimum": Decimal(minimum)},
        )
        await session.commit()


async def _strategy(
    factory: Factory,
    *,
    share: str = "33.5",
    pool: tuple[str, str, str] = BYBIT,
    archived: bool = False,
) -> UUID:
    strategy_id = uuid4()
    exchange, venue, currency = pool
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        enabled=not archived,
    )
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE strategies SET allocation_percent = CAST(:share AS numeric) "
                "WHERE id = :id"
            ),
            {"share": share, "id": strategy_id},
        )
        if archived:
            await session.execute(
                text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
                {"id": strategy_id},
            )
        await session.commit()
    return strategy_id


def _exact(response: Any) -> dict[str, Any]:
    """The ``exact`` object, or a failed ASSERTION when none was served."""
    exact = response.json()["exact"]
    assert exact is not None, "no exact amount was served"
    assert isinstance(exact, dict)
    return exact


def _balance(response: Any) -> dict[str, Any]:
    """The ``balance`` object, or a failed ASSERTION when none was served."""
    balance = response.json()["balance"]
    assert balance is not None, "no balance was served"
    assert isinstance(balance, dict)
    return balance


async def _preview(client: AsyncClient, strategy_id: UUID, share: str | None = None) -> Any:
    params = {} if share is None else {"share": share}
    return await client.get(
        f"/api/strategies/{strategy_id}/share-preview", params=params, headers=_auth()
    )


async def _synced(
    factory: Factory,
    *,
    total: str = "1000",
    available: str = "400",
    pool: tuple[str, str, str] = BYBIT,
    age: timedelta = timedelta(seconds=1),
) -> None:
    await _snapshot(
        factory, *pool, total=total, available=available, observed_at=datetime.now(UTC) - age
    )


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def _rows(factory: Factory, table: str) -> list[tuple[Any, ...]]:
    """Every row of ``table``, whole: a count would not see an UPDATE."""
    async with factory() as session:
        result = await session.execute(text(f"SELECT * FROM {table} ORDER BY 1, 2"))  # noqa: S608
        return [tuple(row) for row in result.all()]


# --- the contract, field by field ------------------------------------------------------


async def test_the_stored_share_is_previewed_against_the_pools_balance(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, share="33.5")
    await _synced(pg_session_factory, total="1000", available="400")

    response = await _preview(client, strategy_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "strategy_id",
        "pool",
        "currency",
        "pool_minimum",
        "balance",
        "exact",
        "steps",
    }
    assert body["strategy_id"] == str(strategy_id)
    assert body["pool"] == {"exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT"}
    assert body["currency"] == "USDT"
    assert body["pool_minimum"] == "5.000000000000000000"
    assert set(body["balance"]) == {"total", "observed_at", "stale"}
    assert body["balance"]["total"] == "1000.000000000000000000"
    assert body["balance"]["stale"] is False
    assert datetime.fromisoformat(body["balance"]["observed_at"]).utcoffset() == timedelta(0)
    assert body["exact"] == {
        "share": "33.5",
        "amount": "335.000000000000000000",
        "below_pool_minimum": False,
    }
    assert len(body["steps"]) == 100
    assert body["steps"][0] == {
        "share": 1,
        "amount": "10.000000000000000000",
        "below_pool_minimum": False,
    }
    assert body["steps"][-1] == {
        "share": 100,
        "amount": "1000.000000000000000000",
        "below_pool_minimum": False,
    }
    assert [step["share"] for step in body["steps"]] == list(range(1, 101))


async def test_a_share_asked_for_is_served_as_exact(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, share="33.5")
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id, share="12.34")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["exact"] == {
        "share": "12.34",
        "amount": "123.400000000000000000",
        "below_pool_minimum": False,
    }
    assert len(body["steps"]) == 100
    assert body["steps"][0]["amount"] == "10.000000000000000000"


@pytest.mark.parametrize(
    ("asked", "echoed"),
    [("33.50", "33.5"), ("100.0", "100"), ("0.0000001", "0.0000001"), ("1e1", "10")],
)
async def test_the_exact_share_is_echoed_in_canonical_plain_notation(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    asked: str,
    echoed: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id, share=asked)

    assert response.status_code == 200, response.text
    assert _exact(response)["share"] == echoed


async def test_the_stored_share_is_echoed_in_canonical_plain_notation_too(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The column is an unscaled numeric: ``33.500`` can be what it holds."""
    strategy_id = await _strategy(pg_session_factory, share="33.500")
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id)

    assert _exact(response)["share"] == "33.5"


@pytest.mark.parametrize(
    ("total", "share", "written"),
    [
        ("333.33", "33.5", "111.665550000000000000"),
        ("10", "33.333333333333333333", "3.333333333333333333"),
        # The two cases above are exact or round the same either way; this one
        # carries a 7 past the eighteenth place, which rounding to nearest would carry.
        # The share itself has 18 decimals (decision 50): it is the product that has more.
        ("2", "33.333333333333333335", "0.666666666666666666"),
    ],
)
async def test_the_amount_is_the_allocations_own_rounded_down(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    total: str,
    share: str,
    written: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory, total=total, available=total)

    response = await _preview(client, strategy_id, share=share)

    amount = _exact(response)["amount"]
    assert amount == written
    assert Decimal(amount) == requested_from_percent(Decimal(total), Decimal(share))


async def test_the_amount_is_of_the_total_not_of_what_is_free(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory, total="1000", available="400")

    response = await _preview(client, strategy_id, share="10")

    assert _exact(response)["amount"] == "100.000000000000000000"


@pytest.mark.parametrize(
    ("total", "amount", "below"),
    [("499", "4.990000000000000000", True), ("500", "5.000000000000000000", False),
     ("501", "5.010000000000000000", False)],
)
async def test_the_minimum_flag_agrees_with_the_allocation_on_both_sides_of_the_limit(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    total: str,
    amount: str,
    below: bool,
) -> None:
    """Snapshots of 499, 500 and 501 at a share of 1 are amounts of 4.99, 5.00 and
    5.01 against a minimum of 5. The real ``decide()`` skips a request of that amount
    as below the pool's minimum for exactly the first."""
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory, total=total, available=total)

    exact = _exact(await _preview(client, strategy_id, share="1"))

    assert exact["amount"] == amount
    assert exact["below_pool_minimum"] is below
    decision = decide(
        CapitalPool(key=BYBIT_KEY, balance=Decimal("100000"), reserved_active=Decimal("0")),
        Money(amount=Decimal(exact["amount"]), currency=Currency.USDT),
        AllocationRules(fill_mode=FillMode.PARTIAL, min_order_size=Decimal("5")),
    )
    skipped = decision.skip_reason is SkipReason.REQUEST_BELOW_MIN_ORDER_SIZE
    assert skipped is below


async def test_a_stale_balance_is_served_marked(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    limit = get_settings().balance_snapshot_max_age_seconds
    strategy_id = await _strategy(pg_session_factory, share="10")
    await _synced(pg_session_factory, age=timedelta(seconds=limit + 60))

    response = await _preview(client, strategy_id)

    assert response.status_code == 200, response.text
    assert _balance(response)["stale"] is True
    assert _balance(response)["total"] == "1000.000000000000000000"
    assert _exact(response)["amount"] == "100.000000000000000000"
    assert len(response.json()["steps"]) == 100


async def test_a_pool_nothing_has_synced_serves_no_amount(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)

    response = await _preview(client, strategy_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["balance"] is None
    assert body["exact"] is None
    assert body["steps"] == []
    assert body["pool_minimum"] == "5.000000000000000000"
    assert "amount" not in response.text, "an amount was served for a pool nothing has synced"


async def test_an_archived_strategy_is_served(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, share="30", archived=True)
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id)

    assert response.status_code == 200, response.text
    assert _exact(response)["share"] == "30"


async def test_each_strategy_answers_its_own_pool(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """S1 on ``bybit/usdt-m/USDT`` and S2 on ``binance/usdt-m/USDT``, with different
    totals and minimums: neither answer carries the other's."""
    await _add_pool(pg_session_factory, BINANCE, "7.5")
    first = await _strategy(pg_session_factory, share="10", pool=BYBIT)
    second = await _strategy(pg_session_factory, share="10", pool=BINANCE)
    await _synced(pg_session_factory, total="1000", available="400", pool=BYBIT)
    await _synced(pg_session_factory, total="250", available="250", pool=BINANCE)

    one = await _preview(client, first)
    two = await _preview(client, second)

    assert one.json()["pool"]["exchange"] == "bybit"
    assert one.json()["pool_minimum"] == "5.000000000000000000"
    assert _balance(one)["total"] == "1000.000000000000000000"
    assert _exact(one)["amount"] == "100.000000000000000000"
    assert two.json()["pool"]["exchange"] == "binance"
    assert two.json()["pool_minimum"] == "7.500000000000000000"
    assert _balance(two)["total"] == "250.000000000000000000"
    assert _exact(two)["amount"] == "25.000000000000000000"


# --- refusals ----------------------------------------------------------------------------


async def test_an_unknown_strategy_is_404_no_such_strategy(client: AsyncClient) -> None:
    response = await _preview(client, uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "no such strategy"}


@pytest.mark.parametrize("asked", ["0", "100.5", "abc", "-1", "NaN", "Infinity"])
async def test_a_share_outside_the_range_is_422_and_no_body_repeats_it(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    asked: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id, share=asked)

    assert response.status_code == 422
    assert "input" not in response.text
    if asked not in {"0", "-1"}:
        assert asked not in response.text, "the rejected value was echoed"


class _NoRowSizing:
    """A ``PoolSizingPort`` that finds no ``capital_pools`` row for any pool.

    The foreign key from ``strategies`` to ``capital_pools`` makes that state
    unbuildable in a real database, and no test here bends the schema to reach it:
    the port's dependency is overridden instead."""

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolSizing | None:
        return None


async def test_a_strategy_whose_pool_has_no_row_is_500_with_one_error_naming_both(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The port answers nothing for the pool (see ``_NoRowSizing``'s docstring)."""
    strategy_id = await _strategy(pg_session_factory)
    app = _app(pg_session_factory)
    app.dependency_overrides[get_pool_sizing] = _NoRowSizing
    caplog.set_level(logging.WARNING)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        response = await _preview(api, strategy_id)

    assert response.status_code == 500
    assert set(response.json()) == {"detail"}
    assert str(strategy_id) not in response.text
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert str(strategy_id) in message
    assert "bybit" in message
    assert "usdt-m" in message
    assert "USDT" in message


async def test_reading_a_stale_or_empty_pool_logs_nothing(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A snapshot that stays old is already the watchdog's ERROR, and a pool nothing
    has synced is a normal answer: a line per page view would be noise."""
    limit = get_settings().balance_snapshot_max_age_seconds
    await _add_pool(pg_session_factory, BINANCE, "7.5")
    fresh = await _strategy(pg_session_factory)
    stale = await _strategy(pg_session_factory, pool=BINANCE)
    empty = await _strategy(pg_session_factory, pool=("pionex", "spot", "USDT"))
    await _synced(pg_session_factory)
    await _synced(
        pg_session_factory,
        pool=BINANCE,
        age=timedelta(seconds=limit + 60),
        total="9",
        available="9",
    )
    caplog.set_level(logging.WARNING)

    for strategy_id in (fresh, stale, empty):
        assert (await _preview(client, strategy_id)).status_code == 200

    assert caplog.records == []


# --- read-only by construction -------------------------------------------------------------


async def test_the_preview_completes_while_the_pools_advisory_lock_is_held(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The lock-hold harness used the other way round: a second connection holds the
    pool's advisory lock (as an allocation in flight would) and the preview must NOT
    wait for it. It takes no lock at all."""
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(BYBIT_KEY))
        task: asyncio.Task[Any] | None = None
        try:
            async with pg_session_factory() as watcher:
                held = await watcher.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted"
                    )
                )
            assert held and held >= 1, "the holder does not hold the pool lock"

            task = asyncio.create_task(_preview(client, strategy_id))
            await asyncio.wait({task}, timeout=_WAIT)

            assert task.done(), "the preview waited for the pool's advisory lock"
            response = task.result()
        finally:
            await holder.rollback()  # releases the pool lock, whatever happened above
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert response.status_code == 200, response.text
    assert _exact(response)["amount"] == "335.000000000000000000"


async def test_the_preview_writes_nothing_and_calls_no_exchange(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every row of the tables the route can reach, before and after, and the two
    ways out of the process (a venue transport and the credential vault) observed:
    neither is ever reached."""
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)
    tables = ["reservations", "pool_balance_snapshots", "capital_pools", "strategies"]
    before = {table: await _rows(pg_session_factory, table) for table in tables}
    assert len(before["capital_pools"]) == 4
    assert len(before["pool_balance_snapshots"]) == 1

    reached: list[str] = []

    def _venue_call(*args: object, **kwargs: object) -> None:
        reached.append("venue transport")
        raise AssertionError("the preview reached an exchange")

    def _vault(*args: object, **kwargs: object) -> None:
        reached.append("credential vault")
        raise AssertionError("the preview reached the credential vault")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _venue_call)
    monkeypatch.setattr(SqlAlchemyCredentialVault, "__init__", _vault)
    monkeypatch.setattr(SqlAlchemyCredentialVault, "load", _vault)

    stored = await _preview(client, strategy_id)
    asked = await _preview(client, strategy_id, share="12.5")

    assert stored.status_code == 200
    assert asked.status_code == 200
    assert reached == []
    assert {table: await _rows(pg_session_factory, table) for table in tables} == before


async def test_the_route_issues_the_same_number_of_statements_for_the_stored_share_and_an_asked_one(
    client: AsyncClient,
    pg_engine: AsyncEngine,  # noqa: F811
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Two reads of the database, and nothing per step: the strategy, then the pool
    with its snapshot. The asked share is arithmetic, not another query."""
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    with _captured_sql(pg_engine) as for_the_stored_share:
        await _preview(client, strategy_id)
    with _captured_sql(pg_engine) as for_an_asked_share:
        await _preview(client, strategy_id, share="12.34")

    assert len(for_the_stored_share) == len(for_an_asked_share)
    assert len(for_the_stored_share) == 2
    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement in for_the_stored_share + for_an_asked_share
    )


async def test_no_share_preview_response_contains_a_json_float_or_an_exponent(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """A micro share on a small total: amounts down in the tenth decimal, the shape
    that makes ``str(Decimal)`` write an exponent. Every leaf is a string, a boolean,
    a null or (only ``share`` of a step) an integer; the raw text parses without a
    float at all."""
    strategy_id = await _strategy(pg_session_factory, share="0.0000001")
    await _synced(pg_session_factory, total="0.5", available="0.5")

    def _no_float(token: str) -> float:
        raise AssertionError(f"a JSON float in the response: {token}")

    for share in (None, "0.0000001"):
        response = await _preview(client, strategy_id, share=share)
        assert response.status_code == 200, response.text
        json.loads(response.text, parse_float=_no_float)
        for path, leaf in _walk(response.json()):
            assert not isinstance(leaf, float), path
            if isinstance(leaf, int) and not isinstance(leaf, bool):
                assert re.fullmatch(r"\$\.steps\[\d+\]\.share", path), path
            # A figure written as text is plain digits: no exponent, no sign.
            is_figure = path.rsplit(".", 1)[-1] in {"amount", "total", "pool_minimum", "share"}
            if is_figure and isinstance(leaf, str):
                assert re.fullmatch(r"\d+(\.\d+)?", leaf), f"{path} is {leaf!r}"
    exact = _exact(response)
    assert exact["share"] == "0.0000001"
    assert exact["amount"] == "0.000000000500000000"
    assert exact["below_pool_minimum"] is True
