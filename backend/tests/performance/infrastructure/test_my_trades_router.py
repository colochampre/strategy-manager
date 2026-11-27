"""API tests for ``GET /api/performance/trades`` [DB]: the signed-in user's CLOSED
operations across every pool they hold ledger rows in (panel-redesign RD.4a).

Mounted through ``create_app()`` over real PostgreSQL. Trades are written through
``RecordFill`` (the production write path); the sources, the read and the
derivations are the real ones, so what is under test is the wire.

**Binding testing lesson.** A symbol has three spellings: the open leg of a Bybit
trade is ``STXUSDT.P`` (TradingView) and its close ``STXUSDT`` (the venue); on
Pionex spot both legs are ``STX_USDT``. Every row answers pair ``STXUSDT``.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from tests.identity_auth import ADMIN_HEADERS, FORGED_HEADERS
from tests.owner import seed_other_user
from tests.performance.infrastructure.conftest import seed_execution_attempt
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    PIONEX,
    _fill,
    _record,
    _seed_allocation,
)
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    _app,
    _json,
    _signed_in,
    _strategy,
    _trade,
)

pytestmark = pytest.mark.integration

URL = "/api/performance/trades"
T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
SPOT_SYMBOLS = ("STX_USDT", "STX_USDT")


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(pg_session_factory)), base_url="http://test"
    ) as api:
        yield api


async def _get(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(URL, headers=ADMIN_HEADERS, params=params)
    assert response.status_code == 200, response.text
    return dict(_json(response))


def _days(n: int) -> datetime:
    return T0 + timedelta(days=n)


def _ids(body: dict[str, Any]) -> list[str]:
    return [row["allocation_id"] for row in body["trades"]]


async def _pool_trade(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    closed_at: datetime,
    pool: PoolKey = BYBIT,
    **kwargs: Any,
) -> UUID:
    if pool == PIONEX:
        kwargs.setdefault("symbols", SPOT_SYMBOLS)
    return await _trade(factory, strategy_id, closed_at, pool=pool, **kwargs)


async def _safety_event(
    factory: async_sessionmaker[AsyncSession],
    allocation_id: UUID,
    strategy_id: UUID,
    kind: str,
    *,
    user_id: UUID | None = None,
) -> None:
    from tests.owner import OWNER_ID

    attempt_id = uuid4()
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
    )
    async with factory() as session:
        session.add(
            SafetyEventRow(
                user_id=user_id or OWNER_ID,
                kind=kind,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                exchange="bybit",
                venue="usdt-m",
                symbol="STXUSDT",
                occurred_at=T0,
                detail={},
                execution_attempt_id=attempt_id,
            )
        )
        await session.commit()


# --- the list across pools --------------------------------------------------------------


async def test_rows_of_two_pools_are_merged_newest_close_first(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bybit = await _strategy(pg_session_factory, BYBIT)
    pionex = await _strategy(pg_session_factory, PIONEX)
    older = await _pool_trade(pg_session_factory, bybit, _days(1))
    newest = await _pool_trade(pg_session_factory, pionex, _days(3), PIONEX)
    middle = await _pool_trade(pg_session_factory, bybit, _days(2))

    body = await _get(client)

    assert _ids(body) == [str(newest), str(middle), str(older)]
    assert body["total"] == 3
    currencies = {row["allocation_id"]: (row["exchange"], row["venue"]) for row in body["trades"]}
    assert currencies[str(newest)] == ("pionex", "spot")
    assert currencies[str(middle)] == ("bybit", "usdt-m")


async def test_a_row_carries_every_field_of_the_contract(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _pool_trade(
        pg_session_factory, strategy_id, _days(1), exit_="110", entry="100"
    )

    body = await _get(client)

    (row,) = body["trades"]
    assert row == {
        "allocation_id": str(allocation_id),
        "strategy_id": str(strategy_id),
        "strategy_name": f"strategy-{strategy_id}",
        "strategy_archived": False,
        "strategy_page": "AUTHORED",
        "exchange": "bybit",
        "venue": "usdt-m",
        "currency": "USDT",
        "pair": "STXUSDT",
        "direction": "LONG",
        "opened_at": (_days(1) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "closed_at": _days(1).isoformat().replace("+00:00", "Z"),
        "rehearsal": False,
        "entry_price": "100.000000000000000000",
        "exit_price": "110.000000000000000000",
        "pnl": "10.000000000000000000",
        "fees_complete": True,
        "close_cause": "SIGNAL",
    }


async def test_no_figure_is_summed_across_pools(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Rule 7: the body has no total of any kind, and each row keeps its own pnl."""
    bybit = await _strategy(pg_session_factory, BYBIT)
    pionex = await _strategy(pg_session_factory, PIONEX)
    one = await _pool_trade(pg_session_factory, bybit, _days(1), exit_="110")
    two = await _pool_trade(pg_session_factory, pionex, _days(2), PIONEX, exit_="130")

    body = await _get(client)

    assert set(body) == {"trades", "total", "strategies", "exchanges"}
    pnl = {row["allocation_id"]: Decimal(row["pnl"]) for row in body["trades"]}
    assert pnl == {str(one): Decimal("10"), str(two): Decimal("30")}


# --- paging -----------------------------------------------------------------------------


async def test_total_counts_before_the_page_cut(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    made = [await _pool_trade(pg_session_factory, strategy_id, _days(n)) for n in range(1, 6)]
    newest_first = [str(a) for a in reversed(made)]

    first = await _get(client, limit=2)
    second = await _get(client, limit=2, offset=2)
    last = await _get(client, limit=2, offset=4)
    beyond = await _get(client, limit=2, offset=10)

    assert _ids(first) == newest_first[0:2]
    assert _ids(second) == newest_first[2:4]
    assert _ids(last) == newest_first[4:5]
    assert beyond["trades"] == []
    assert [b["total"] for b in (first, second, last, beyond)] == [5, 5, 5, 5]


async def test_the_default_page_is_twenty(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    for n in range(21):
        await _pool_trade(pg_session_factory, strategy_id, _days(n))

    body = await _get(client)

    assert len(body["trades"]) == 20
    assert body["total"] == 21


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"closed_since": "2026-09-21T12:00:00"},
        {"strategy_id": "not-a-uuid"},
    ],
)
async def test_a_bad_query_is_a_422(client: AsyncClient, params: dict[str, Any]) -> None:
    response = await client.get(URL, headers=ADMIN_HEADERS, params=params)

    assert response.status_code == 422, response.text


async def test_the_route_requires_a_signed_in_user(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(URL, headers=FORGED_HEADERS)).status_code == 401


# --- filters ----------------------------------------------------------------------------


async def test_closed_since_keeps_operations_closed_at_or_after_it(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _pool_trade(pg_session_factory, strategy_id, _days(1))
    on_the_line = await _pool_trade(pg_session_factory, strategy_id, _days(2))
    after = await _pool_trade(pg_session_factory, strategy_id, _days(3))

    body = await _get(client, closed_since=_days(2).isoformat())

    assert _ids(body) == [str(after), str(on_the_line)]
    assert body["total"] == 2


async def test_strategy_and_exchange_filters_alone_and_combined(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bybit_a = await _strategy(pg_session_factory, BYBIT)
    bybit_b = await _strategy(pg_session_factory, BYBIT)
    pionex = await _strategy(pg_session_factory, PIONEX)
    a1 = await _pool_trade(pg_session_factory, bybit_a, _days(1))
    b1 = await _pool_trade(pg_session_factory, bybit_b, _days(2))
    p1 = await _pool_trade(pg_session_factory, pionex, _days(3), PIONEX)

    only_a = await _get(client, strategy_id=str(bybit_a))
    only_bybit = await _get(client, exchange="bybit")
    only_pionex = await _get(client, exchange="pionex")
    mismatch = await _get(client, strategy_id=str(pionex), exchange="bybit")
    both = await _get(
        client, strategy_id=str(bybit_b), exchange="bybit", closed_since=_days(2).isoformat()
    )

    assert _ids(only_a) == [str(a1)]
    assert _ids(only_bybit) == [str(b1), str(a1)]
    assert _ids(only_pionex) == [str(p1)]
    assert mismatch["trades"] == [] and mismatch["total"] == 0
    assert _ids(both) == [str(b1)]
    assert both["total"] == 1


async def test_strategies_and_exchanges_do_not_shrink_with_the_filters(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bybit = await _strategy(pg_session_factory, BYBIT)
    pionex = await _strategy(pg_session_factory, PIONEX)
    async with pg_session_factory() as session:
        for strategy_id, name in ((bybit, "Zeta"), (pionex, "Alpha")):
            await session.execute(
                text("UPDATE strategies SET name = :n WHERE id = :id"),
                {"n": name, "id": strategy_id},
            )
        await session.execute(
            text("UPDATE strategies SET archived_at = now() WHERE id = :id"), {"id": pionex}
        )
        await session.commit()
    await _pool_trade(pg_session_factory, bybit, _days(1))
    await _pool_trade(pg_session_factory, pionex, _days(2), PIONEX)
    expected_strategies = [
        {"id": str(pionex), "name": "Alpha", "archived": True},
        {"id": str(bybit), "name": "Zeta", "archived": False},
    ]

    unfiltered = await _get(client)
    narrowed = await _get(
        client, strategy_id=str(bybit), exchange="bybit", closed_since=_days(9).isoformat()
    )

    for body in (unfiltered, narrowed):
        assert body["strategies"] == expected_strategies
        assert body["exchanges"] == ["bybit", "pionex"]
    assert narrowed["trades"] == []


async def test_an_archived_strategy_is_named_and_flagged_on_its_rows(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _pool_trade(pg_session_factory, strategy_id, _days(1))
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET archived_at = now() WHERE id = :id"), {"id": strategy_id}
        )
        await session.commit()

    body = await _get(client)

    assert body["trades"][0]["strategy_archived"] is True


# --- scope ------------------------------------------------------------------------------


async def test_another_users_operations_never_appear(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await _strategy(pg_session_factory, BYBIT)
    theirs = await _strategy(pg_session_factory, PIONEX)
    own = await _pool_trade(pg_session_factory, mine, _days(1))
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    await _pool_trade(pg_session_factory, theirs, _days(2), PIONEX, user_id=other)
    await _pool_trade(pg_session_factory, mine, _days(3), user_id=other)

    body = await _get(client)

    assert _ids(body) == [str(own)]
    assert body["total"] == 1
    assert [s["id"] for s in body["strategies"]] == [str(mine)]
    assert body["exchanges"] == ["bybit"]


# --- close cause ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["STOP_FIRED", "STOP_FAILED_CLOSED", "STRATEGY_STOPPED_CLOSED", "MANUAL_CLOSE"]
)
async def test_close_cause_is_the_kind_of_the_operations_close_event(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession], kind: str
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    with_event = await _pool_trade(pg_session_factory, strategy_id, _days(1))
    without = await _pool_trade(pg_session_factory, strategy_id, _days(2))
    await _safety_event(pg_session_factory, with_event, strategy_id, kind)

    body = await _get(client)

    causes = {row["allocation_id"]: row["close_cause"] for row in body["trades"]}
    assert causes == {str(with_event): kind, str(without): "SIGNAL"}


async def test_an_opening_refusal_event_is_not_a_close_cause(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _pool_trade(pg_session_factory, strategy_id, _days(1))
    await _safety_event(
        pg_session_factory, allocation_id, strategy_id, "OPENING_REFUSED_LEVERAGE_CAP"
    )

    body = await _get(client)

    assert body["trades"][0]["close_cause"] == "SIGNAL"


async def test_another_users_event_on_the_same_allocation_is_not_a_cause(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _pool_trade(pg_session_factory, strategy_id, _days(1))
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    await _safety_event(pg_session_factory, allocation_id, strategy_id, "STOP_FIRED", user_id=other)

    body = await _get(client)

    assert body["trades"][0]["close_cause"] == "SIGNAL"


# --- rehearsal --------------------------------------------------------------------------


async def test_a_rehearsal_operation_is_listed_and_flagged(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    real = await _pool_trade(pg_session_factory, strategy_id, _days(1))
    _, dry, attempt = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=dry,
            attempt_id=attempt,
            side="BUY",
            quantity="1",
            price="1",
            symbol="STXUSDT.P",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
            filled_at=_days(2) - timedelta(hours=1),
        ),
        _fill(
            strategy_id=strategy_id,
            allocation_id=dry,
            attempt_id=attempt,
            side="SELL",
            quantity="1",
            price="1",
            symbol="STXUSDT",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
            filled_at=_days(2),
        ),
    )

    body = await _get(client)

    flags = {row["allocation_id"]: row["rehearsal"] for row in body["trades"]}
    assert flags == {str(dry): True, str(real): False}
    assert body["total"] == 2
