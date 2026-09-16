"""Integration test: reading capital_pools returns the seeded rows
(tasks.md 3.6)."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

pytestmark = pytest.mark.integration


async def test_list_enabled_returns_the_four_seeded_pools(pg_engine: AsyncEngine) -> None:
    async with pg_engine.connect() as conn:
        pools = await CapitalPoolRepository(conn).list_enabled()

    by_key = {(p.venue, p.settlement_currency): p for p in pools}
    assert len(pools) == 4
    assert by_key[(Venue.SPOT, Currency.USDT)].min_order_size == Decimal("10")
    assert by_key[(Venue.USDT_M, Currency.USDT)].min_order_size == Decimal("5")
    assert by_key[(Venue.COIN_M, Currency.BTC)].min_order_size == Decimal("0.0001")
    assert by_key[(Venue.COIN_M, Currency.ETH)].min_order_size == Decimal("0.001")
    assert all(p.enabled for p in pools)


async def test_seeded_pools_carry_the_exchange_they_were_backfilled_with(
    pg_engine: AsyncEngine,
) -> None:
    """usdt-m is the venue this system has actually traded, and it traded it on
    Bybit; spot and coin-m are the Pionex-era pools."""
    async with pg_engine.connect() as conn:
        pools = await CapitalPoolRepository(conn).list_enabled()

    by_key = {(p.venue, p.settlement_currency): p for p in pools}
    assert by_key[(Venue.USDT_M, Currency.USDT)].exchange == Exchange.BYBIT
    assert by_key[(Venue.SPOT, Currency.USDT)].exchange == Exchange.PIONEX
    assert by_key[(Venue.COIN_M, Currency.BTC)].exchange == Exchange.PIONEX
