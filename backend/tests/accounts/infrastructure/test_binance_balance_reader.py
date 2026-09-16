"""``BinanceBalanceReader`` — mapping the USDⓈ-M futures wallet onto pools.

Binance segregates wallets, so the mapping is where a wrong answer becomes a
position sized against money that is somewhere else.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.accounts.infrastructure.binance_balance_reader import (
    BinanceBalanceReader,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.binance.read_client import (
    FuturesAssetBalance,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

USDT_M_POOL = ("binance", "usdt-m", "USDT")
SPOT_POOL = ("binance", "spot", "USDT")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeClient:
    def __init__(self, *assets: FuturesAssetBalance) -> None:
        self.calls = 0
        self._assets = list(assets)

    async def futures_assets(self) -> list[FuturesAssetBalance]:
        self.calls += 1
        return self._assets


def _asset(
    asset: str = "USDT",
    wallet: str = "642.02208358",
    available: str = "635.82694163",
) -> FuturesAssetBalance:
    return FuturesAssetBalance(
        asset=asset,
        wallet_balance=Decimal(wallet),
        available_balance=Decimal(available),
        unrealized_profit=Decimal("0"),
        position_initial_margin=Decimal("0"),
        open_order_initial_margin=Decimal("0"),
    )


def _reader(*assets: FuturesAssetBalance) -> tuple[BinanceBalanceReader, FakeClient]:
    client = FakeClient(*assets)
    return BinanceBalanceReader(client, FrozenClock()), client  # type: ignore[arg-type]


async def test_a_futures_pool_reads_the_futures_wallet() -> None:
    reader, _ = _reader(_asset())

    readings = await reader.read([USDT_M_POOL])

    assert readings[0].total == Decimal("642.02208358")
    assert readings[0].available == Decimal("635.82694163")


async def test_every_reading_is_stamped_binance() -> None:
    """The snapshot row has to say which exchange answered, or Bybit's
    usdt-m/USDT and Binance's become one pool again."""
    reader, _ = _reader(_asset())

    readings = await reader.read([USDT_M_POOL])

    assert readings[0].exchange == "binance"


async def test_a_spot_pool_is_refused_rather_than_answered_from_futures() -> None:
    """Binance keeps the wallets apart. Answering a spot pool from the futures
    account would report another wallet's money -- the Pionex bug in reverse."""
    reader, client = _reader(_asset())

    with pytest.raises(InvariantViolation, match="USDⓈ-M futures wallet only"):
        await reader.read([SPOT_POOL])

    assert client.calls == 0


async def test_the_refusal_happens_before_the_network_call() -> None:
    """A configuration that cannot be served safely should not spend a request
    finding that out."""
    reader, client = _reader(_asset())

    with pytest.raises(InvariantViolation):
        await reader.read([USDT_M_POOL, SPOT_POOL])

    assert client.calls == 0


async def test_a_currency_the_account_does_not_hold_reads_as_zero() -> None:
    reader, _ = _reader(_asset(asset="USDT"))

    readings = await reader.read([("binance", "usdt-m", "USDC")])

    assert readings[0].total == Decimal(0)
    assert readings[0].available == Decimal(0)


async def test_the_account_is_fetched_once_however_many_pools_there_are() -> None:
    reader, client = _reader(_asset(), _asset(asset="USDC", wallet="10", available="10"))

    await reader.read([USDT_M_POOL, ("binance", "usdt-m", "USDC")])

    assert client.calls == 1


async def test_every_reading_shares_one_observation_time() -> None:
    reader, _ = _reader(_asset(), _asset(asset="USDC", wallet="10", available="10"))

    readings = await reader.read([USDT_M_POOL, ("binance", "usdt-m", "USDC")])

    assert {reading.observed_at for reading in readings} == {NOW}
