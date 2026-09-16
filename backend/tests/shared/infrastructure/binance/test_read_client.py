"""Parsing Binance's USDⓈ-M futures account payload.

The numbers here are the ones the live account actually returned on
2026-09-15, with a 0.1 AAVE short open: they are what settled which field a
pool's total and availability come from.
"""

from decimal import Decimal

import pytest

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import (
    ACCOUNT_PATH,
    BinanceReadOnlyClient,
    FuturesAssetBalance,
)

# The live USDT asset with an isolated AAVE short open.
LIVE_USDT = {
    "asset": "USDT",
    "walletBalance": "642.02208358",
    "unrealizedProfit": "-0.00559325",
    "marginBalance": "642.01649033",
    "availableBalance": "635.82694163",
    "positionInitialMargin": "6.20129663",
    "openOrderInitialMargin": "0.00000000",
}


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.signed_paths: list[str] = []

    async def get_signed(self, path: str, params: object = None) -> object:
        self.signed_paths.append(path)
        return self.payload


def _client(payload: object) -> tuple[BinanceReadOnlyClient, FakeTransport]:
    client = BinanceReadOnlyClient.__new__(BinanceReadOnlyClient)
    transport = FakeTransport(payload)
    client._transport = transport  # type: ignore[attr-defined]
    return client, transport


async def test_the_account_is_read_from_the_signed_futures_endpoint() -> None:
    client, transport = _client({"assets": [LIVE_USDT]})

    await client.futures_assets()

    assert transport.signed_paths == [ACCOUNT_PATH]


async def test_every_amount_keeps_its_full_precision() -> None:
    """Binance sends amounts as strings. Parsed through float, 642.02828208
    would round, and the rounding would land in a position size."""
    client, _ = _client({"assets": [LIVE_USDT]})

    usdt = (await client.futures_assets())[0]

    assert usdt.wallet_balance == Decimal("642.02208358")
    assert usdt.available_balance == Decimal("635.82694163")
    assert usdt.unrealized_profit == Decimal("-0.00559325")
    assert usdt.position_initial_margin == Decimal("6.20129663")


async def test_the_total_is_the_wallet_including_committed_margin() -> None:
    """The margin behind the open position stays in walletBalance, so a
    second strategy sizes from the same base as the first."""
    client, _ = _client({"assets": [LIVE_USDT]})

    usdt = (await client.futures_assets())[0]

    assert usdt.total == Decimal("642.02208358")


async def test_availability_is_the_wallet_minus_the_margin_actually_committed() -> None:
    client, _ = _client({"assets": [LIVE_USDT]})

    usdt = (await client.futures_assets())[0]

    assert usdt.available == Decimal("635.82694163")


async def test_availability_never_exceeds_the_total() -> None:
    """In CROSS mode Binance can fold unrealized profit into availableBalance.
    A pool whose availability exceeded its total would violate the snapshot's
    own CHECK, so the cap is the conservative reading."""
    balance = FuturesAssetBalance(
        asset="USDT",
        wallet_balance=Decimal("1000"),
        available_balance=Decimal("1050"),
        unrealized_profit=Decimal("50"),
        position_initial_margin=Decimal("0"),
        open_order_initial_margin=Decimal("0"),
    )

    assert balance.total == Decimal("1000")
    assert balance.available == Decimal("1000")


def test_a_negative_wallet_reads_as_zero_not_as_a_debt() -> None:
    balance = FuturesAssetBalance(
        asset="USDT",
        wallet_balance=Decimal("-5"),
        available_balance=Decimal("-5"),
        unrealized_profit=Decimal("0"),
        position_initial_margin=Decimal("0"),
        open_order_initial_margin=Decimal("0"),
    )

    assert balance.total == Decimal(0)
    assert balance.available == Decimal(0)


async def test_an_account_with_no_assets_list_is_refused() -> None:
    client, _ = _client({"totalWalletBalance": "642"})

    with pytest.raises(BinanceApiError, match="no 'assets' list"):
        await client.futures_assets()


async def test_a_missing_amount_is_refused_rather_than_defaulted() -> None:
    """A missing balance read as zero is a pool that silently stops trading."""
    client, _ = _client({"assets": [{"asset": "USDT", "walletBalance": "1"}]})

    with pytest.raises(BinanceApiError, match="availableBalance"):
        await client.futures_assets()


async def test_an_unparsable_amount_is_refused() -> None:
    client, _ = _client({"assets": [{**LIVE_USDT, "walletBalance": "n/a"}]})

    with pytest.raises(BinanceApiError, match="not a number"):
        await client.futures_assets()
