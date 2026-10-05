"""API tests for the performance endpoints [DB] (design.md sections 11 and 14;
tasks.md 7.2):

- ``GET /api/performance/pools/{exchange}/{venue}/{ccy}``
- ``GET /api/performance/strategies/{id}``
- ``GET /api/performance/strategies/{id}/trades``

Mounted through ``create_app()`` so the ``/api`` prefix is part of what is
proven, over a real PostgreSQL session. Trades are written through
``RecordFill`` (the production write path), and the fills source, the reads and
the derivation are the real ones: what is under test is the wire.

**Binding testing lesson.** A symbol has three spellings. The open leg of a
trade below is ``STXUSDT.P`` (TradingView), its close is ``STXUSDT`` (the
venue), and on Pionex spot both are ``STX_USDT``. The API answers under the one
``market_key`` form.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.main import create_app
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.infrastructure.performance_router import (
    get_clock,
    get_fills_source,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.performance.fakes import FakeFillsSource, FixedClock
from tests.performance.infrastructure.conftest import seed_strategy
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    PIONEX,
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"
NOW = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
DAY1 = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
COIN_M_BTC = PoolKey(Exchange.PIONEX, Venue.COIN_M, Currency.BTC)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


class _Json(dict[str, Any]):
    """A response body whose missing key is a failed ASSERTION (the body is
    wrong), not a ``KeyError``."""

    def __missing__(self, key: str) -> Any:
        raise AssertionError(f"key {key!r} is not in the response; it holds {sorted(self)}")


def _json(response: Response) -> _Json:
    body = response.json()
    assert isinstance(body, dict), f"expected an object, got {body!r}"
    return _Json(body)


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


def _app(factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    app.dependency_overrides[get_clock] = lambda: FixedClock(NOW)
    return app


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(pg_session_factory)), base_url="http://test"
    ) as api:
        yield api


# --- seeding ---------------------------------------------------------------------------


async def _strategy(factory: async_sessionmaker[AsyncSession], pool: PoolKey = BYBIT) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        exchange=pool.exchange.value,
        venue=pool.venue.value,
        settlement_currency=pool.settlement_currency.value,
    )
    return strategy_id


async def _trade(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    closed_at: datetime,
    *,
    pool: PoolKey = BYBIT,
    opened_by: str = "BUY",
    entry: str = "100",
    exit_: str = "110",
    quantity: str = "1",
    capital: str | None = "1000",
    symbols: tuple[str, str] = ("STXUSDT.P", "STXUSDT"),
) -> UUID:
    """One closed allocation of ``strategy_id``: opened one hour before
    ``closed_at`` by ``opened_by`` at ``entry`` and closed at ``exit_``."""
    _, allocation_id, attempt_id = await _seed_allocation(
        factory, pool=pool, pool_total_at_open=capital, strategy_id=strategy_id
    )
    closing = "SELL" if opened_by == "BUY" else "BUY"
    await _record(
        factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side=opened_by,
            quantity=quantity,
            price=entry,
            symbol=symbols[0],
            filled_at=closed_at - timedelta(hours=1),
            pool=pool,
        ),
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side=closing,
            quantity=quantity,
            price=exit_,
            symbol=symbols[1],
            filled_at=closed_at,
            pool=pool,
        ),
    )
    return allocation_id


def _walk(node: Any, path: str = "$") -> list[tuple[str, Any]]:
    """Every leaf of a JSON document with its path."""
    if isinstance(node, dict):
        return [leaf for key, value in node.items() for leaf in _walk(value, f"{path}.{key}")]
    if isinstance(node, list):
        return [leaf for i, value in enumerate(node) for leaf in _walk(value, f"{path}[{i}]")]
    return [(path, node)]


POOL_URL = "/api/performance/pools/bybit/usdt-m/USDT"


# --- authentication and routing --------------------------------------------------------


async def test_get_pool_performance_requires_bearer_token(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """All three routes refuse a missing or wrong token with the one 401, and
    none exists outside ``/api``. Discovered per route, not assumed from the
    pool route alone."""
    strategy_id = await _strategy(pg_session_factory)
    urls = [
        POOL_URL,
        f"/api/performance/strategies/{strategy_id}",
        f"/api/performance/strategies/{strategy_id}/trades",
    ]
    for url in urls:
        missing = await client.get(url)
        wrong = await client.get(url, headers={"Authorization": f"Bearer {TOKEN}-wrong"})
        admitted = await client.get(url, headers=_auth())
        pre_move = await client.get(url.removeprefix("/api"), headers=_auth())

        assert missing.status_code == 401, url
        assert wrong.status_code == 401, url
        assert missing.json()["detail"] == UNAUTHORIZED_DETAIL, url
        assert admitted.status_code == 200, url
        assert pre_move.status_code == 404, url


async def test_get_pool_performance_404_unknown_pool(client: AsyncClient) -> None:
    """Unknown means "not a row of ``capital_pools``": a well-formed pool that
    is not configured, an exchange that does not exist, and a wrong case."""
    for url in (
        "/api/performance/pools/pionex/usdt-m/USDT",
        "/api/performance/pools/kraken/spot/USDT",
        "/api/performance/pools/bybit/usdt-m/usdt",
        "/api/performance/pools/bybit/usdt-m/DOGE",
    ):
        response = await client.get(url, headers=_auth())

        assert response.status_code == 404, url
        assert response.json() == {"detail": "no such pool"}, url

    known = await client.get(POOL_URL, headers=_auth())
    assert known.status_code == 200


async def test_pool_performance_of_a_disabled_pool_is_still_readable(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A pool the owner switched off keeps its history."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1)
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE capital_pools SET enabled = false WHERE exchange = 'bybit'")
        )
        await session.commit()

    response = await client.get(POOL_URL, headers=_auth())

    assert response.status_code == 200
    assert _json(response)["trade_count"] == 1


# --- the pool report -------------------------------------------------------------------


async def test_get_pool_performance_returns_curve_drawdown_monthly_and_ranges(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Design section 11's worked example on a 1,000 USDT pool. Day 1: +20 and
    +10, both against 1,000, sum to R = 0.03 (not chained). Day 2: -20.6
    against 1,030 is r = -0.02. The clock is fixed at 2026-09-30, so the 7D
    window holds nothing and the 30D window holds everything."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="120")
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="110")
    await _trade(pg_session_factory, strategy_id, DAY2, exit_="79.4", capital="1030")

    response = await client.get(POOL_URL, headers=_auth())

    assert response.status_code == 200
    body = _json(response)
    assert body["pool"] == {"exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT"}
    assert body["currency"] == "USDT"
    assert body["day_boundary"] == "UTC"
    assert body["trade_count"] == 3
    assert Decimal(body["total_pnl"]) == Decimal("9.4")
    assert body["max_drawdown"] == "-0.0200000000"
    assert body["curve"] == [
        {
            "date": "2026-09-21",
            "daily_return": "0.0300000000",
            "index": "1.0300000000",
            "drawdown": "0.0000000000",
        },
        {
            "date": "2026-09-22",
            "daily_return": "-0.0200000000",
            "index": "1.0094000000",
            "drawdown": "-0.0200000000",
        },
    ]
    assert body["monthly"] == [{"year": 2026, "month": 9, "return": "0.0094000000"}]
    ranges = {r["range"]: r for r in body["ranges"]}
    assert list(ranges) == ["7D", "30D", "90D", "1Y", "All"]
    assert (Decimal(ranges["7D"]["pnl"]), ranges["7D"]["return"], ranges["7D"]["trade_count"]) == (
        Decimal("0"),
        "0.0000000000",
        0,
    )
    for name in ("30D", "90D", "1Y", "All"):
        assert Decimal(ranges[name]["pnl"]) == Decimal("9.4"), name
        assert ranges[name]["return"] == "0.0094000000", name
        assert ranges[name]["trade_count"] == 3, name


async def test_pool_performance_trades_without_capital_count_in_pnl_not_in_the_curve(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The production shape: two reservations from before migration 0026 have no
    ``pool_total_at_open``. Their PnL is real and is returned; they have no
    return, so they never reach the curve; and the exclusion is reported."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="110", capital=None)
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="105", capital=None)
    await _trade(pg_session_factory, strategy_id, DAY2, exit_="120", capital="1000")

    response = await client.get(POOL_URL, headers=_auth())

    body = _json(response)
    assert body["trade_count"] == 3
    assert Decimal(body["total_pnl"]) == Decimal("35")
    assert body["excluded"]["no_capital_at_open"] == 2
    assert [point["date"] for point in body["curve"]] == ["2026-09-22"]
    assert body["curve"][0]["index"] == "1.0200000000"
    all_time = {r["range"]: r for r in body["ranges"]}["All"]
    assert Decimal(all_time["pnl"]) == Decimal("35")
    assert all_time["return"] == "0.0200000000"


async def test_pool_performance_reports_every_exclusion(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Decision 17: "the exclusions are reported". One open allocation, one
    rehearsal fill, one closed trade whose fee is in a third currency, and one
    allocation with a symbol that has no base in the pool's currency."""
    strategy_id = await _strategy(pg_session_factory)
    open_alloc = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=open_alloc[1],
            attempt_id=open_alloc[2],
            side="BUY",
            quantity="1",
            filled_at=DAY1,
        ),
    )
    rehearsal = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=rehearsal[1],
            attempt_id=rehearsal[2],
            side="BUY",
            quantity="1",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}1",
            filled_at=DAY1,
        ),
    )
    third = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=third[1],
            attempt_id=third[2],
            side="BUY",
            quantity="1",
            fee="0.1",
            fee_currency="BNB",
            filled_at=DAY1 - timedelta(hours=1),
        ),
        _fill(
            strategy_id=strategy_id,
            allocation_id=third[1],
            attempt_id=third[2],
            side="SELL",
            quantity="1",
            price="110",
            filled_at=DAY1,
        ),
    )
    odd = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=odd[1],
            attempt_id=odd[2],
            side="BUY",
            quantity="1",
            symbol="BTCEUR",
            filled_at=DAY1,
        ),
    )

    response = await client.get(POOL_URL, headers=_auth())

    body = _json(response)
    assert body["excluded"] == {
        "open_trade_count": 1,
        "rehearsal_fill_count": 1,
        "no_capital_at_open": 0,
        "unconverted_fee": 1,
        "unresolved_allocation_count": 1,
    }
    assert body["trade_count"] == 1


async def test_two_pools_on_one_exchange_are_reported_separately(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Rule 7. Pionex spot/USDT and Pionex coin-m/BTC: each report holds only
    its own trade and its own currency, and no field combines them."""
    spot = await _strategy(pg_session_factory, PIONEX)
    await _trade(
        pg_session_factory,
        spot,
        DAY1,
        pool=PIONEX,
        exit_="110",
        symbols=("STX_USDT", "STX_USDT"),
    )
    coin_m_strategy = await _strategy(pg_session_factory, COIN_M_BTC)
    await _trade(
        pg_session_factory,
        coin_m_strategy,
        DAY1,
        pool=COIN_M_BTC,
        entry="0.5",
        exit_="0.75",
        capital="2",
        symbols=("ETHBTC.P", "ETHBTC"),
    )

    usdt = _json(await client.get("/api/performance/pools/pionex/spot/USDT", headers=_auth()))
    btc = _json(await client.get("/api/performance/pools/pionex/coin-m/BTC", headers=_auth()))

    assert (usdt["currency"], usdt["trade_count"], Decimal(usdt["total_pnl"])) == (
        "USDT",
        1,
        Decimal("10"),
    )
    assert (btc["currency"], btc["trade_count"], Decimal(btc["total_pnl"])) == (
        "BTC",
        1,
        Decimal("0.25"),
    )
    assert "total" not in usdt and "total" not in btc


# --- the strategy report ---------------------------------------------------------------


async def test_get_strategy_performance_includes_by_pair(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Two trades of one market spelled differently (``STXUSDT.P`` open,
    ``STXUSDT`` close; ``STXUSDT_PERP`` both) are ONE pair; a second market is a
    second row. The strategy's curve is its contribution to the POOL."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="120")
    await _trade(
        pg_session_factory,
        strategy_id,
        DAY2,
        exit_="90",
        symbols=("STXUSDT_PERP", "STXUSDT_PERP"),
    )
    await _trade(
        pg_session_factory, strategy_id, DAY2, exit_="105", symbols=("ETHUSDT.P", "ETHUSDT")
    )

    response = await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 200
    body = _json(response)
    assert body["strategy_id"] == str(strategy_id)
    assert body["currency"] == "USDT"
    assert body["trade_count"] == 3
    assert Decimal(body["total_pnl"]) == Decimal("15")
    pairs = {p["pair"]: p for p in body["by_pair"]}
    assert list(pairs) == ["ETHUSDT", "STXUSDT"]
    assert pairs["STXUSDT"]["trades"] == 2
    assert Decimal(pairs["STXUSDT"]["pnl"]) == Decimal("10")
    # +20 on day 1 (r = 0.02) then -10 on day 2 (r = -0.01): 1.02 * 0.99 = 1.0098.
    assert pairs["STXUSDT"]["return"] == "0.0098000000"
    assert (pairs["ETHUSDT"]["trades"], Decimal(pairs["ETHUSDT"]["pnl"])) == (1, Decimal("5"))


async def test_strategy_performance_holds_only_that_strategys_trades(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Two strategies in ONE pool: each report is its own slice, the pool report
    is both."""
    mine = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, mine, DAY1, exit_="110")
    await _trade(pg_session_factory, other, DAY1, exit_="150")

    mine_body = _json(
        await client.get(f"/api/performance/strategies/{mine}", headers=_auth())
    )
    other_body = _json(
        await client.get(f"/api/performance/strategies/{other}", headers=_auth())
    )
    pool_body = _json(await client.get(POOL_URL, headers=_auth()))

    assert Decimal(mine_body["total_pnl"]) == Decimal("10")
    assert Decimal(other_body["total_pnl"]) == Decimal("50")
    assert Decimal(pool_body["total_pnl"]) == Decimal("60")


async def test_strategy_endpoints_answer_404_for_an_unknown_strategy(
    client: AsyncClient,
) -> None:
    unknown = uuid4()
    for suffix in ("", "/trades"):
        response = await client.get(
            f"/api/performance/strategies/{unknown}{suffix}", headers=_auth()
        )

        assert response.status_code == 404, suffix
        assert response.json() == {"detail": "no such strategy"}, suffix

    malformed = await client.get("/api/performance/strategies/not-a-uuid", headers=_auth())
    assert malformed.status_code == 422


async def test_an_archived_strategy_still_returns_its_performance_and_trades(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Decisions 11 and 14: archiving hides a strategy from the active list, it
    does not erase its history."""
    strategy_id = await _strategy(pg_session_factory)
    allocation_id = await _trade(pg_session_factory, strategy_id, DAY1, exit_="110")
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET archived_at = now(), enabled = false WHERE id = :id"),
            {"id": strategy_id},
        )
        await session.commit()

    performance = await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())
    trades = await client.get(
        f"/api/performance/strategies/{strategy_id}/trades", headers=_auth()
    )

    assert performance.status_code == 200
    assert _json(performance)["trade_count"] == 1
    assert trades.status_code == 200
    assert [t["allocation_id"] for t in _json(trades)["trades"]] == [str(allocation_id)]


async def test_strategy_endpoints_read_the_strategys_own_pool_never_one_from_the_request(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A wrong pool yields an empty result, not an error, so the router is what
    binds strategy to pool. Two strategies in two pools; the source records the
    pool each read asked for."""
    bybit_strategy = await _strategy(pg_session_factory, BYBIT)
    pionex_strategy = await _strategy(pg_session_factory, PIONEX)
    source = FakeFillsSource([])
    app = _app(pg_session_factory)
    app.dependency_overrides[get_fills_source] = lambda: source

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        for strategy_id in (bybit_strategy, pionex_strategy):
            for suffix in ("", "/trades"):
                response = await api.get(
                    f"/api/performance/strategies/{strategy_id}{suffix}", headers=_auth()
                )
                assert response.status_code == 200, suffix

    assert source.asked == [BYBIT, BYBIT, PIONEX, PIONEX]


# --- the trades list -------------------------------------------------------------------


async def test_get_strategy_trades_item_shape_and_direction(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    long_id = await _trade(pg_session_factory, strategy_id, DAY1, exit_="110")
    short_id = await _trade(
        pg_session_factory, strategy_id, DAY2, opened_by="SELL", entry="100", exit_="94"
    )
    no_capital = await _trade(
        pg_session_factory, strategy_id, DAY2 - timedelta(hours=3), capital=None
    )

    response = await client.get(
        f"/api/performance/strategies/{strategy_id}/trades", headers=_auth()
    )

    assert response.status_code == 200
    body = _json(response)
    items = {t["allocation_id"]: t for t in body["trades"]}
    assert [t["allocation_id"] for t in body["trades"]] == [
        str(short_id),
        str(no_capital),
        str(long_id),
    ]
    assert body["next_cursor"] is None
    short = items[str(short_id)]
    assert short == {
        "allocation_id": str(short_id),
        "pair": "STXUSDT",
        "direction": "SHORT",
        "opened_at": "2026-09-22T11:00:00Z",
        "closed_at": "2026-09-22T12:00:00Z",
        "rehearsal": False,
        "rehearsal_fill_price": None,
        "base_currency": "STX",
        "entry_price": "100.000000000000000000",
        "exit_price": "94.000000000000000000",
        "size": "1.000000000000000000",
        "fees": "0.000000000000000000",
        "other_fees": [],
        "pnl": short["pnl"],
        "capital_at_open": short["capital_at_open"],
        "return": "0.0060000000",
        "fees_complete": True,
    }
    assert Decimal(short["pnl"]) == Decimal("6")
    assert Decimal(short["capital_at_open"]) == Decimal("1000")
    assert items[str(long_id)]["direction"] == "LONG"
    assert items[str(no_capital)]["capital_at_open"] is None
    assert items[str(no_capital)]["return"] is None
    assert Decimal(items[str(no_capital)]["pnl"]) == Decimal("10")


async def test_get_strategy_trades_keyset_pagination_walks_every_trade_once(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The "+1ms" lesson over HTTP: three trades close at the very same instant,
    one 1 ms later and one 1 ms earlier, and the page size is two, so page edges
    fall between tied trades. The cursor is fed back exactly as the response
    gave it, as two query parameters."""
    strategy_id = await _strategy(pg_session_factory)
    close = datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=UTC)
    ms = timedelta(milliseconds=1)
    tied = [await _trade(pg_session_factory, strategy_id, close) for _ in range(3)]
    later = await _trade(pg_session_factory, strategy_id, close + ms)
    earlier = await _trade(pg_session_factory, strategy_id, close - ms)
    expected = [later, *sorted(tied, reverse=True), earlier]

    walked: list[UUID] = []
    params: dict[str, str] = {"limit": "2"}
    pages = 0
    while True:
        response = await client.get(
            f"/api/performance/strategies/{strategy_id}/trades", params=params, headers=_auth()
        )
        assert response.status_code == 200, response.text
        body = _json(response)
        walked += [UUID(t["allocation_id"]) for t in body["trades"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert set(cursor) == {"before_closed_at", "before_allocation_id"}
        params = {"limit": "2", **cursor}

    assert walked == expected
    assert pages == 3


async def test_get_strategy_trades_keyset_pagination_422_half_a_cursor(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Half a cursor, a cursor without a time zone, and a page size outside
    1..200 are all the caller's input and all 422. Each is refused for the right
    reason (the body says which), and a good cursor is not."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1)
    url = f"/api/performance/strategies/{strategy_id}/trades"
    # Strictly before the trade's close, so the ordering (not a random id) decides.
    when, allocation = "2026-09-21T11:00:00Z", str(uuid4())

    only_time = await client.get(url, params={"before_closed_at": when}, headers=_auth())
    only_id = await client.get(url, params={"before_allocation_id": allocation}, headers=_auth())
    naive = await client.get(
        url,
        params={"before_closed_at": "2026-09-21T12:00:00", "before_allocation_id": allocation},
        headers=_auth(),
    )
    good = await client.get(
        url,
        params={"before_closed_at": when, "before_allocation_id": allocation},
        headers=_auth(),
    )

    assert only_time.status_code == 422
    assert "before_allocation_id" in only_time.text
    assert only_id.status_code == 422
    assert "before_closed_at" in only_id.text
    assert naive.status_code == 422
    assert "time zone" in naive.text
    assert good.status_code == 200
    assert [t["allocation_id"] for t in _json(good)["trades"]] == []


async def test_get_strategy_trades_page_size_defaults_to_50_max_200_else_422(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    for minute in range(51):
        await _trade(pg_session_factory, strategy_id, DAY1 + timedelta(minutes=minute))
    url = f"/api/performance/strategies/{strategy_id}/trades"

    default = _json(await client.get(url, headers=_auth()))
    largest = await client.get(url, params={"limit": "200"}, headers=_auth())
    zero = await client.get(url, params={"limit": "0"}, headers=_auth())
    over = await client.get(url, params={"limit": "201"}, headers=_auth())
    word = await client.get(url, params={"limit": "many"}, headers=_auth())

    assert len(default["trades"]) == 50
    assert default["next_cursor"] is not None
    assert largest.status_code == 200
    assert len(_json(largest)["trades"]) == 51
    assert _json(largest)["next_cursor"] is None
    assert (zero.status_code, over.status_code, word.status_code) == (422, 422, 422)


# --- empty ledgers ---------------------------------------------------------------------


def _assert_empty_report(body: dict[str, Any], *, rehearsal: int = 0) -> None:
    assert body["trade_count"] == 0
    assert Decimal(body["total_pnl"]) == Decimal("0")
    assert body["max_drawdown"] == "0.0000000000"
    assert body["curve"] == []
    assert body["monthly"] == []
    assert body["excluded"] == {
        "open_trade_count": 0,
        "rehearsal_fill_count": rehearsal,
        "no_capital_at_open": 0,
        "unconverted_fee": 0,
        "unresolved_allocation_count": 0,
    }
    assert [r["range"] for r in body["ranges"]] == ["7D", "30D", "90D", "1Y", "All"]
    for entry in body["ranges"]:
        assert Decimal(entry["pnl"]) == Decimal("0")
        assert entry["return"] == "0.0000000000"
        assert entry["trade_count"] == 0


async def test_empty_ledger_returns_zeros_and_empty_arrays_never_an_error(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A pool nothing has traded in, a strategy that has never traded, and the
    trade list of that strategy: all 200, all zeros or empty."""
    strategy_id = await _strategy(pg_session_factory)

    pool = await client.get(POOL_URL, headers=_auth())
    strategy = await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())
    trades = await client.get(
        f"/api/performance/strategies/{strategy_id}/trades", headers=_auth()
    )

    assert pool.status_code == strategy.status_code == trades.status_code == 200
    _assert_empty_report(_json(pool))
    strategy_body = _json(strategy)
    _assert_empty_report(strategy_body)
    assert strategy_body["by_pair"] == []
    assert _json(trades) == {"trades": [], "next_cursor": None}


async def test_a_ledger_holding_only_rehearsal_fills_is_empty_and_says_how_many_it_left_out(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    _, allocation_id, attempt_id = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id
    )
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="1",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}a",
            filled_at=DAY1,
        ),
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="SELL",
            quantity="1",
            price="120",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}b",
            filled_at=DAY2,
        ),
    )

    pool = _json(await client.get(POOL_URL, headers=_auth()))
    strategy = _json(
        await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())
    )

    _assert_empty_report(pool, rehearsal=2)
    _assert_empty_report(strategy, rehearsal=2)


# --- the wire --------------------------------------------------------------------------


async def test_no_response_contains_a_json_float_and_every_decimal_is_a_plain_string(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Money, quantities and ratios are JSON strings, never numbers (the
    ``_amount()`` rule), and none is written in scientific notation: a
    break-even trade's PnL is ``"0"``-like, not ``"0E-18"``. Timestamps carry an
    explicit UTC designator. Every response of every route is walked, including
    ``GET /api/pools``."""
    strategy_id = await _strategy(pg_session_factory)
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="100")  # break-even
    await _trade(pg_session_factory, strategy_id, DAY1, exit_="107.3")
    await _trade(pg_session_factory, strategy_id, DAY2, exit_="93.1", capital=None)
    urls = [
        "/api/pools",
        POOL_URL,
        f"/api/performance/strategies/{strategy_id}",
        f"/api/performance/strategies/{strategy_id}/trades",
    ]

    leaves: list[tuple[str, Any]] = []
    for url in urls:
        response = await client.get(url, headers=_auth())
        assert response.status_code == 200, url
        leaves += [(f"{url} {path}", value) for path, value in _walk(response.json())]

    assert len(leaves) > 60
    floats = [(path, value) for path, value in leaves if isinstance(value, float)]
    assert floats == []
    for path, value in leaves:
        if isinstance(value, str):
            try:
                number = Decimal(value)
            except ArithmeticError:
                continue
            assert number.is_finite(), path
            assert "e" not in value.lower(), f"{path} is written in scientific notation: {value}"
        if path.endswith(("opened_at", "closed_at", "observed_at")) and value is not None:
            parsed = datetime.fromisoformat(value)
            assert parsed.utcoffset() == timedelta(0), path
            assert value.endswith("Z"), path


# --- integrity faults ------------------------------------------------------------------


async def test_a_source_that_returns_another_pools_rows_is_a_500_and_one_logged_error(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """Rule 7 is a refusal, and a refusal must leave a trace. The read raises,
    the router answers 500 with a fixed body that echoes nothing, and exactly one
    ERROR carries the reason."""
    stray = FillGroup(
        allocation_id=uuid4(),
        strategy_id=uuid4(),
        exchange="pionex",
        venue="spot",
        settlement_currency="USDT",
        symbol="STX_USDT",
        side="BUY",
        fee_currency="USDT",
        quantity=Decimal("1"),
        notional=Decimal("100"),
        fee=Decimal("0"),
        first_filled_at=DAY1,
        last_filled_at=DAY1,
        pool_total_at_open=Decimal("1000"),
        rehearsal=False,
    )
    app = _app(pg_session_factory)
    app.dependency_overrides[get_fills_source] = lambda: FakeFillsSource([stray])

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get(POOL_URL, headers=_auth())

    assert response.status_code == 500
    assert response.json() == {"detail": "performance data failed an integrity check"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "pools are never blended" in errors[0].getMessage()
