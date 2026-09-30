"""``SqlAlchemyCapitalPoolWriter`` against real PostgreSQL (unit 6d, decision 21).

The writer takes an exchange and nothing else. Which pool that means, and the
``min_order_size`` a row created from scratch starts with, come from
``KNOWN_FUTURES_POOLS``. The database is seeded by this package's conftest
(mirroring migration 0003): ``bybit/usdt-m/USDT`` exists and is enabled at 5,
``binance/usdt-m/USDT`` does NOT exist, so both the flip and the insert paths
are reachable.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.domain import known_pools
from strategy_manager.accounts.domain.known_pools import KNOWN_FUTURES_POOLS, KnownPool
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

pytestmark = pytest.mark.integration

Identity = tuple[str, str, str]
BYBIT: Identity = ("bybit", "usdt-m", "USDT")
BINANCE: Identity = ("binance", "usdt-m", "USDT")


async def _snapshot(
    factory: async_sessionmaker[AsyncSession],
) -> dict[Identity, tuple[bool, Decimal]]:
    async with factory() as session:
        rows = (await session.execute(select(CapitalPoolRow))).scalars()
        return {
            (r.exchange, r.venue, r.settlement_currency): (r.enabled, r.min_order_size)
            for r in rows
        }


async def _set_pool(
    factory: async_sessionmaker[AsyncSession],
    identity: Identity,
    *,
    enabled: bool,
    min_order_size: str,
) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, "
                "enabled, min_order_size) VALUES (:e, :v, :c, :enabled, :m) "
                "ON CONFLICT (exchange, venue, settlement_currency) DO UPDATE SET "
                "enabled = :enabled, min_order_size = :m"
            ),
            {
                "e": identity[0],
                "v": identity[1],
                "c": identity[2],
                "enabled": enabled,
                "m": min_order_size,
            },
        )
        await session.commit()


async def test_enable_upserts_from_known_futures_pools_constant_never_request_body(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await _snapshot(pg_session_factory)
    async with pg_session_factory() as session:
        changed = await SqlAlchemyCapitalPoolWriter(session).enable("binance")
        await session.commit()
    after = await _snapshot(pg_session_factory)

    known = KNOWN_FUTURES_POOLS[Exchange.BINANCE]
    created = set(after) - set(before)
    assert changed is True
    assert created == {("binance", known.venue.value, known.settlement_currency.value)}
    assert {k: v for k, v in after.items() if k in before} == before, "another pool changed"


async def test_enable_reads_the_identity_from_the_constant_at_call_time(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different constant gives a different pool: nothing in the writer names
    a venue or a currency of its own."""
    monkeypatch.setattr(
        known_pools,
        "KNOWN_FUTURES_POOLS",
        {Exchange.BINANCE: KnownPool(Venue.COIN_M, Currency.ETH, Decimal("0.5"))},
    )
    async with pg_session_factory() as session:
        await SqlAlchemyCapitalPoolWriter(session).enable("binance")
        await session.commit()

    assert (await _snapshot(pg_session_factory)).get(("binance", "coin-m", "ETH")) == (
        True,
        Decimal("0.5"),
    )


async def test_enable_on_missing_row_inserts_with_default_min_order_size(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default that differs from anything hard-coded, so a literal in the
    writer cannot pass by coincidence."""
    monkeypatch.setattr(
        known_pools,
        "KNOWN_FUTURES_POOLS",
        {Exchange.BINANCE: KnownPool(Venue.USDT_M, Currency.USDT, Decimal("8.5"))},
    )
    async with pg_session_factory() as session:
        await SqlAlchemyCapitalPoolWriter(session).enable("binance")
        await session.commit()

    assert (await _snapshot(pg_session_factory)).get(BINANCE) == (True, Decimal("8.5"))


async def test_enable_on_a_disabled_row_flips_only_enabled_and_keeps_min_order_size(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_pool(pg_session_factory, BINANCE, enabled=False, min_order_size="7.25")
    before = await _snapshot(pg_session_factory)

    async with pg_session_factory() as session:
        changed = await SqlAlchemyCapitalPoolWriter(session).enable("binance")
        await session.commit()
    after = await _snapshot(pg_session_factory)

    assert changed is True
    assert after[BINANCE] == (True, Decimal("7.25"))
    assert {k: v for k, v in after.items() if k != BINANCE} == {
        k: v for k, v in before.items() if k != BINANCE
    }


async def test_enable_on_an_already_enabled_row_is_a_no_op_that_says_so(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_pool(pg_session_factory, BYBIT, enabled=True, min_order_size="7.25")
    before = await _snapshot(pg_session_factory)

    async with pg_session_factory() as session:
        writer = SqlAlchemyCapitalPoolWriter(session)
        first = await writer.enable("bybit")
        second = await writer.enable("bybit")
        await session.commit()

    assert (first, second) == (False, False)
    assert await _snapshot(pg_session_factory) == before


async def test_enable_is_part_of_the_callers_transaction_and_rolls_back_with_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_pool(pg_session_factory, BYBIT, enabled=False, min_order_size="5")

    async with pg_session_factory() as session:
        await SqlAlchemyCapitalPoolWriter(session).enable("bybit")
        await SqlAlchemyCapitalPoolWriter(session).enable("binance")
        await session.rollback()

    after = await _snapshot(pg_session_factory)
    assert after[BYBIT][0] is False
    assert BINANCE not in after


@pytest.mark.parametrize("exchange", ["pionex", "kraken"])
async def test_enable_for_an_exchange_without_a_known_pool_raises_and_changes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], exchange: str
) -> None:
    before = await _snapshot(pg_session_factory)

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation):
            await SqlAlchemyCapitalPoolWriter(session).enable(exchange)
        await session.commit()

    assert await _snapshot(pg_session_factory) == before


async def test_disable_flips_only_the_existing_row_and_keeps_min_order_size(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_pool(pg_session_factory, BYBIT, enabled=True, min_order_size="7.25")
    before = await _snapshot(pg_session_factory)

    async with pg_session_factory() as session:
        writer = SqlAlchemyCapitalPoolWriter(session)
        first = await writer.disable("bybit")
        second = await writer.disable("bybit")
        await session.commit()
    after = await _snapshot(pg_session_factory)

    assert (first, second) == (True, False)
    assert after[BYBIT] == (False, Decimal("7.25"))
    assert {k: v for k, v in after.items() if k != BYBIT} == {
        k: v for k, v in before.items() if k != BYBIT
    }


async def test_disable_on_a_missing_row_creates_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    before = await _snapshot(pg_session_factory)
    assert BINANCE not in before

    async with pg_session_factory() as session:
        changed = await SqlAlchemyCapitalPoolWriter(session).disable("binance")
        await session.commit()

    assert changed is False
    assert await _snapshot(pg_session_factory) == before
