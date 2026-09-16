"""Implements ``ExchangeBalanceReaderPort`` over the read-only Binance client.

**Binance segregates wallets**, like Pionex and unlike Bybit: spot, USDⓈ-M
futures, COIN-M futures, margin, funding and earn are separate balances moved
between by an explicit transfer (verified live 2026-09-15 -- the account showed
~3675 USDT on spot and 642 in USDⓈ-M futures at the same moment).

So a venue here selects a WALLET, and this reader speaks to exactly one of
them: USDⓈ-M futures. A ``spot`` or ``coin-m`` pool on Binance is refused
rather than answered from the futures account, because answering it would
report one wallet's money as another's -- the Pionex bug that sized a futures
strategy against a spot balance, in reverse.

Failing the balance sync is the right severity: a pool whose availability
cannot be read stops trading, which is what should happen when the alternative
is sizing real orders against a balance that is not there.
"""

from collections.abc import Sequence
from decimal import Decimal

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Exchange, Venue
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
    FuturesAssetBalance,
)

SERVED_VENUE = Venue.USDT_M.value


class BinanceBalanceReader:
    """Reads the USDⓈ-M futures balances backing the configured pools."""

    def __init__(self, client: BinanceReadOnlyClient, clock: ClockPort) -> None:
        self._client = client
        self._clock = clock

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        """Fetches the futures account once, however many pools draw on it.

        ``observed_at`` is stamped once for the whole batch: every reading
        comes from a single response, so a per-pool timestamp would imply a
        precision that is not there.
        """
        _assert_every_pool_is_futures(pools)

        by_asset = {
            balance.asset.upper(): balance
            for balance in await self._client.futures_assets()
        }
        observed_at = self._clock.now()

        return [
            PoolBalanceReading(
                exchange=exchange,
                venue=venue,
                settlement_currency=currency,
                total=_total(by_asset.get(currency.upper())),
                available=_available(by_asset.get(currency.upper())),
                observed_at=observed_at,
            )
            for exchange, venue, currency in pools
        ]


def _assert_every_pool_is_futures(pools: Sequence[PoolKey]) -> None:
    """Refuses a pool this reader cannot honestly answer.

    Binance keeps the spot and futures wallets apart, so reporting a spot
    pool's balance from the futures account would be a number about a
    different pot of money.
    """
    wrong = sorted(
        {f"{exchange}/{venue}" for exchange, venue, _ in pools if venue != SERVED_VENUE}
    )
    if wrong:
        raise InvariantViolation(
            f"BinanceBalanceReader reads the USDⓈ-M futures wallet only, but was "
            f"asked for {', '.join(wrong)}. Binance keeps spot, futures, margin and "
            "funding as separate balances, so answering from the futures account "
            f"would report another wallet's money. Enable only {Exchange.BINANCE.value}"
            f"/{SERVED_VENUE} pools, or add the adapter for the wallet you want."
        )


def _total(balance: FuturesAssetBalance | None) -> Decimal:
    """An asset the account does not mention reads as zero, not as an error.

    Binance lists every supported margin asset, funded or not, so this is the
    conservative reading of a currency it omitted rather than a failure -- and
    a pool with nothing in it is a pool the allocator skips.
    """
    return Decimal(0) if balance is None else balance.total


def _available(balance: FuturesAssetBalance | None) -> Decimal:
    return Decimal(0) if balance is None else balance.available
