"""API tests for a pair's wins [DB] (design.md, unit 12f addendum, section G;
spec: performance-reporting "A Pair's Win Rate Counts Closed Operations With A
PnL Above Zero", admin-api "The Strategy Performance Route Serves Each Pair's
Wins And Win Rate"; tasks.md 12f.9.2).

``GET /api/performance/strategies/{id}`` serves ``wins`` (an integer) and
``win_rate`` (the wire's ``Ratio``: a string with 10 places) on each ``by_pair``
entry. Mounted through ``create_app()`` over real PostgreSQL on the ORM schema:
the report is a read, and no constraint or index the ORM schema lacks decides
an outcome. Fills are written through ``RecordFill``; the source, the read, the
derivation and the wire are the real ones.

**Binding testing lesson.** A symbol has three spellings. The real operations of
the first strategy open as ``STXUSDT.P`` (TradingView's) and close as
``STXUSDT`` (the venue's); the second strategy's are written ``STXUSDT_PERP``
(Pionex's) on both legs. Every entry is asserted under the pair ``STXUSDT`` and
no assertion compares two spellings as text.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from tests.performance.infrastructure.conftest import _rehearsal_id
from tests.performance.infrastructure.test_allocation_fills_source import (
    BINANCE,
    BYBIT,
    _fill,
    _record,
    _seed_allocation,
)
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    DAY1,
    POOL_URL,
    _app,
    _auth,
    _configure_admin_token,
    _json,
    _strategy,
    _trade,
    _walk,
)

pytestmark = pytest.mark.integration

REAL_SPELLINGS = ("STXUSDT.P", "STXUSDT")
PIONEX_SPELLINGS = ("STXUSDT_PERP", "STXUSDT_PERP")


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(pg_session_factory)), base_url="http://test"
    ) as api:
        yield api


async def _operations(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    exits: tuple[str, ...],
    *,
    pool: PoolKey = BYBIT,
    symbols: tuple[str, str] = REAL_SPELLINGS,
) -> None:
    """One closed real operation per exit price: opened at 100 for a quantity of
    1 (no fee), so the PnL is ``exit - 100``. Each closes two hours after the
    previous one."""
    for index, exit_price in enumerate(exits):
        await _trade(
            factory,
            strategy_id,
            DAY1 + timedelta(hours=2 * index),
            pool=pool,
            exit_=exit_price,
            symbols=symbols,
        )


async def _rehearsal_operations(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID, exits: tuple[str, ...]
) -> None:
    """Closed DRY_RUN operations (the fill ids carry the rehearsal prefix)."""
    for index, exit_price in enumerate(exits):
        _, allocation_id, attempt_id = await _seed_allocation(factory, strategy_id=strategy_id)
        closed_at = DAY1 + timedelta(hours=2 * index)
        await _record(
            factory,
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="1",
                price="100",
                symbol="STXUSDT_PERP",
                filled_at=closed_at - timedelta(hours=1),
                fill_id=_rehearsal_id(),
            ),
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="SELL",
                quantity="1",
                price=exit_price,
                symbol="STXUSDT.P",
                filled_at=closed_at,
                fill_id=_rehearsal_id(),
            ),
        )


async def _report(client: AsyncClient, strategy_id: UUID) -> dict[str, Any]:
    response = await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())
    assert response.status_code == 200, response.text
    return dict(_json(response))


async def _by_pair(client: AsyncClient, strategy_id: UUID) -> list[dict[str, Any]]:
    return list((await _report(client, strategy_id))["by_pair"])


async def test_a_pair_carries_its_wins_and_its_rate(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Five closed operations: three above zero, one at exactly zero, one below.
    The zero is not a win and still counts in the total."""
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("110", "105", "102", "100", "99"))

    entries = await _by_pair(client, strategy_id)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["wins"] == 3
    assert entry["win_rate"] == "0.6000000000"
    assert entry["pair"] == "STXUSDT"
    assert entry["trades"] == 5
    assert Decimal(entry["pnl"]) == Decimal("16")
    assert entry["return"] is not None


async def test_a_pair_with_no_win_has_a_zero_rate_not_a_null(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("90", "100"))

    entries = await _by_pair(client, strategy_id)

    assert [(e["pair"], e["trades"], e["wins"], e["win_rate"]) for e in entries] == [
        ("STXUSDT", 2, 0, "0.0000000000")
    ]


async def test_a_pair_that_won_every_operation_has_a_rate_of_one(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("101", "130", "100.5"))

    entries = await _by_pair(client, strategy_id)

    assert [(e["pair"], e["trades"], e["wins"], e["win_rate"]) for e in entries] == [
        ("STXUSDT", 3, 3, "1.0000000000")
    ]


async def test_a_win_count_never_exceeds_the_trade_count_in_any_entry(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("110", "90", "100"))
    await _operations(
        pg_session_factory,
        strategy_id,
        ("120",),
        symbols=("ETHUSDT.P", "ETHUSDT"),
    )

    entries = await _by_pair(client, strategy_id)

    assert [e["pair"] for e in entries] == ["ETHUSDT", "STXUSDT"]
    assert [(e["trades"], e["wins"]) for e in entries] == [(1, 1), (3, 1)]
    for entry in entries:
        assert 0 <= entry["wins"] <= entry["trades"]


async def test_no_pair_row_is_served_for_a_pair_with_no_closed_operation(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """An operation that is still open has no closed trade: no row, and no zero
    invented for it."""
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
            price="100",
            symbol="STXUSDT.P",
            filled_at=DAY1,
        ),
    )

    report = await _report(client, strategy_id)

    assert report["excluded"]["open_trade_count"] == 1
    assert report["by_pair"] == []


async def test_each_by_pair_entry_carries_exactly_the_documented_keys(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("110", "90"))

    entries = await _by_pair(client, strategy_id)

    assert len(entries) == 1
    assert sorted(entries[0]) == ["pair", "pnl", "return", "trades", "win_rate", "wins"]


async def test_the_strategy_and_pool_reports_gain_no_win_rate(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Decision 44 names the By pair table only: neither the strategy's own
    figures nor the pool report carry ``wins`` or ``win_rate`` outside
    ``by_pair``."""
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("110", "90"))

    strategy_report = await _report(client, strategy_id)
    pool_report = _json(await client.get(POOL_URL, headers=_auth()))

    assert strategy_report["by_pair"][0]["wins"] == 1
    for report in (strategy_report, dict(pool_report)):
        outside = [
            path
            for path, _ in _walk(report)
            if (path.endswith(".wins") or path.endswith(".win_rate"))
            and not path.startswith("$.by_pair[")
        ]
        assert outside == []


async def test_two_strategies_on_two_pools_are_not_blended(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """S1 on ``bybit/usdt-m/USDT``, S2 on ``binance/usdt-m/USDT``, both on the
    pair ``STXUSDT``. Each rate comes from its own operations: S1 won one of two,
    S2 won none."""
    # The shared fixtures seed no Binance pool; the foreign key of a strategy needs it.
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools "
                "(exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('binance', 'usdt-m', 'USDT', 5)"
            )
        )
        await session.commit()
    bybit_strategy = await _strategy(pg_session_factory, BYBIT)
    binance_strategy = await _strategy(pg_session_factory, BINANCE)
    await _operations(pg_session_factory, bybit_strategy, ("110", "90"))
    await _operations(
        pg_session_factory,
        binance_strategy,
        ("95", "80", "100"),
        pool=BINANCE,
        symbols=PIONEX_SPELLINGS,
    )

    bybit_entries = await _by_pair(client, bybit_strategy)
    binance_entries = await _by_pair(client, binance_strategy)

    assert [(e["pair"], e["trades"], e["wins"], e["win_rate"]) for e in bybit_entries] == [
        ("STXUSDT", 2, 1, "0.5000000000")
    ]
    assert [(e["pair"], e["trades"], e["wins"], e["win_rate"]) for e in binance_entries] == [
        ("STXUSDT", 3, 0, "0.0000000000")
    ]


async def test_the_wins_are_the_same_with_and_without_rehearsal_groups_in_the_ledger(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Decision 43: DRY_RUN operations are not the strategy's record. Three closed
    rehearsal operations above zero on the same pair change nothing."""
    strategy_id = await _strategy(pg_session_factory)
    await _operations(pg_session_factory, strategy_id, ("110", "90"))
    before = await _by_pair(client, strategy_id)

    await _rehearsal_operations(pg_session_factory, strategy_id, ("120", "130", "140"))
    after = await _by_pair(client, strategy_id)

    assert [(e["pair"], e["trades"], e["wins"], e["win_rate"]) for e in before] == [
        ("STXUSDT", 2, 1, "0.5000000000")
    ]
    assert after == before
