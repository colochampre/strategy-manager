"""``GET /api/public/strategies/{id}/record``: the curve, the months, the ranges and the
pairs of a public strategy's record, with no money in them (tasks.md I.12a, decisions
28, 34 and 40) [DB].

Each test goes through the application's route over real PostgreSQL. The clock is
fixed, so a window is the same on every day the suite runs.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from strategy_manager.main import create_app
from strategy_manager.performance.infrastructure.performance_router import get_clock
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS, seed_admin, sign_in_as_admin
from tests.performance.fakes import FixedClock
from tests.performance.infrastructure.test_public_strategies_router import (
    LIST,
    T0,
    Factory,
    _crafted_record,
    _new_user,
    _not_listed,
    _strategy,
    _subscribe,
    _trade,
)

NOW = T0 + timedelta(days=2)

#: The body is an explicit list. Anything added to it has to be added here too.
RECORD_KEYS = {
    "day_boundary",
    "origin",
    "closed_trade_count",
    "max_drawdown",
    "ranges",
    "curve",
    "monthly",
    "by_pair",
}


@pytest.fixture(autouse=True)
def _signed_in_with_the_brake_off(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "dry_run", False)


async def _get(factory: Factory, path: str, headers: dict[str, str] = OTHER_HEADERS) -> Response:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    app.dependency_overrides[get_clock] = lambda: FixedClock(NOW)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def _record(factory: Factory, strategy_id: UUID) -> dict[str, Any]:
    response = await _get(factory, f"{LIST}/{strategy_id}/record")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _two_overlapping_trades(factory: Factory, author: UUID, strategy_id: UUID) -> None:
    """+10 % and +5 % on one UTC day, the second opened half an hour into the first."""
    await _trade(factory, author, strategy_id, bought="100", sold="110", at=T0)
    await _trade(
        factory, author, strategy_id, bought="100", sold="105", at=T0 + timedelta(minutes=30)
    )


async def test_any_signed_in_user_reads_the_record_of_a_public_strategy_and_only_its_fields(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _two_overlapping_trades(pg_session_factory, author, strategy_id)

    stranger = await _get(pg_session_factory, f"{LIST}/{strategy_id}/record", OTHER_HEADERS)
    admin = await _get(pg_session_factory, f"{LIST}/{strategy_id}/record", ADMIN_HEADERS)

    assert stranger.status_code == admin.status_code == 200
    assert set(stranger.json()) == RECORD_KEYS
    assert stranger.json() == admin.json()


async def test_the_record_lays_out_the_curve_the_months_the_ranges_and_the_pairs(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _two_overlapping_trades(pg_session_factory, author, strategy_id)

    body = await _record(pg_session_factory, strategy_id)

    assert body["day_boundary"] == "UTC"
    assert body["origin"] == "2026-09-01"
    assert body["closed_trade_count"] == 2
    assert body["max_drawdown"] == "0.0000000000"
    assert body["curve"] == [
        {
            "date": "2026-09-01",
            "daily_return": "0.1500000000",
            "index": "1.1500000000",
            "drawdown": "0.0000000000",
        }
    ]
    assert body["monthly"] == [{"year": 2026, "month": 9, "return": "0.1500000000"}]
    assert body["ranges"] == [
        {"range": name, "return": "0.1500000000", "trade_count": 2}
        for name in ("7D", "30D", "90D", "1Y", "All")
    ]
    assert body["by_pair"] == [
        {
            "pair": "STXUSDT",
            "trades": 2,
            "wins": 2,
            "win_rate": "1.0000000000",
            "return": "0.1500000000",
        }
    ]


async def test_a_window_counts_only_the_trades_closed_inside_it(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _trade(
        pg_session_factory,
        author,
        strategy_id,
        bought="100",
        sold="110",
        at=NOW - timedelta(days=10),
    )
    await _trade(
        pg_session_factory,
        author,
        strategy_id,
        bought="100",
        sold="90",
        at=NOW - timedelta(days=1),
    )

    body = await _record(pg_session_factory, strategy_id)

    assert [(each["range"], each["return"], each["trade_count"]) for each in body["ranges"]] == [
        ("7D", "-0.1000000000", 1),
        ("30D", "-0.0100000000", 2),
        ("90D", "-0.0100000000", 2),
        ("1Y", "-0.0100000000", 2),
        ("All", "-0.0100000000", 2),
    ]


async def test_the_record_carries_no_money_anywhere(pg_session_factory: Factory) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _subscribe(pg_session_factory, author, strategy_id, share="50", total="4321")
    await _two_overlapping_trades(pg_session_factory, author, strategy_id)

    body = await _record(pg_session_factory, strategy_id)

    def keys(node: Any) -> Iterator[str]:
        if isinstance(node, dict):
            for name, child in node.items():
                yield name
                yield from keys(child)
        elif isinstance(node, list):
            for child in node:
                yield from keys(child)

    for name in keys(body):
        for money in ("pnl", "amount", "capital", "fee", "size", "total", "currency"):
            assert money not in name, name
    assert "4321" not in str(body)


async def test_a_rehearsal_fill_and_a_subscribers_fill_never_count(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    subscriber = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _trade(pg_session_factory, author, strategy_id, sold="150", rehearsal=True)
    await _trade(pg_session_factory, subscriber, strategy_id, bought="100", sold="150")
    await _trade(pg_session_factory, author, strategy_id, bought="100", sold="90")

    body = await _record(pg_session_factory, strategy_id)

    assert body["closed_trade_count"] == 1
    assert [each["index"] for each in body["curve"]] == ["0.9000000000"]
    assert body["max_drawdown"] == "-0.1000000000"
    assert [each["trades"] for each in body["by_pair"]] == [1]


async def test_a_strategy_with_no_closed_real_trade_answers_an_empty_report(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _trade(pg_session_factory, author, strategy_id, sold=None)

    body = await _record(pg_session_factory, strategy_id)

    assert body["origin"] is None
    assert body["closed_trade_count"] == 0
    assert (body["curve"], body["monthly"], body["by_pair"]) == ([], [], [])
    assert body["max_drawdown"] == "0.0000000000"
    assert [(each["return"], each["trade_count"]) for each in body["ranges"]] == [
        ("0.0000000000", 0)
    ] * 5


@pytest.mark.parametrize("case", ["private", "archived", "unnamed author"])
async def test_a_strategy_off_the_public_list_answers_the_404_of_an_unknown_one(
    case: str, pg_session_factory: Factory
) -> None:
    author = await _new_user(pg_session_factory)
    target = (await _not_listed(pg_session_factory, author))[case]
    await _trade(pg_session_factory, author, target)

    response = await _get(pg_session_factory, f"{LIST}/{target}/record")
    unknown = await _get(pg_session_factory, f"{LIST}/{uuid4()}/record")

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_the_author_of_a_private_strategy_gets_the_same_404(
    pg_session_factory: Factory,
) -> None:
    async with pg_session_factory() as session:
        admin = await seed_admin(session)
        await session.commit()
    private = await _strategy(pg_session_factory, admin, visibility="PRIVATE")

    response = await _get(pg_session_factory, f"{LIST}/{private}/record", ADMIN_HEADERS)

    assert response.status_code == 404


async def test_a_record_the_wire_cannot_write_answers_as_off_the_list(
    pg_session_factory: Factory,
) -> None:
    author = await _new_user(pg_session_factory)
    crafted = await _strategy(pg_session_factory, author)
    await _crafted_record(pg_session_factory, author, crafted)

    response = await _get(pg_session_factory, f"{LIST}/{crafted}/record")
    unknown = await _get(pg_session_factory, f"{LIST}/{uuid4()}/record")

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_the_record_is_its_own_strategys(pg_session_factory: Factory) -> None:
    author = await _new_user(pg_session_factory)
    quiet = await _strategy(pg_session_factory, author, created_at=T0)
    traded = await _strategy(pg_session_factory, author, created_at=T0 + timedelta(days=1))
    await _trade(pg_session_factory, author, traded)

    assert (await _record(pg_session_factory, quiet))["closed_trade_count"] == 0
    assert (await _record(pg_session_factory, traded))["closed_trade_count"] == 1


async def test_the_read_runs_in_one_read_only_snapshot_and_touches_no_signal(
    pg_session_factory: Factory, pg_engine: AsyncEngine
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _trade(pg_session_factory, author, strategy_id)
    path = f"{LIST}/{strategy_id}/record"
    await _get(pg_session_factory, path)  # the stranger's own row is written here
    statements: list[str] = []

    def _capture(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        response = await _get(pg_session_factory, path)
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", _capture)

    assert response.status_code == 200
    transaction = [each for each in statements if "SET TRANSACTION" in each]
    assert transaction == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
    assert not [each for each in statements if "signals" in each or "raw_payload" in each]
