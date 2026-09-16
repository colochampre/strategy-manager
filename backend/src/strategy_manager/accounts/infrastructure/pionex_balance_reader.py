"""Implements ``ExchangeBalanceReaderPort`` over the read-only Pionex client.

Maps Pionex's per-coin wallet view onto this system's per-pool view. The two
do not line up on their own: Pionex reports coins per product, while a pool is
``(venue, settlement_currency)``. Spot pools read the spot wallet, USDT-M and
COIN-M pools read the futures wallet, and the pool's settlement currency
selects the coin.
"""

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.money import Venue
from strategy_manager.shared.infrastructure.pionex.read_client import (
    CoinBalance,
    PionexReadOnlyClient,
)

_FUTURES_VENUES = frozenset({Venue.USDT_M.value, Venue.COIN_M.value})


class PionexBalanceReader:
    """Reads the balances backing the configured pools, in one pass."""

    def __init__(self, client: PionexReadOnlyClient, clock: ClockPort) -> None:
        self._client = client
        self._clock = clock

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        """Fetches each wallet at most once, no matter how many pools draw on
        it, so the number of configured pools never multiplies API calls.

        ``observed_at`` is stamped once for the whole batch. The wallets are
        fetched microseconds apart and the freshness window is measured in
        tens of seconds, so a per-wallet timestamp would imply a precision
        that is not really there.
        """
        venues = {venue for _exchange, venue, _currency in pools}
        spot = await self._by_coin(self._client.spot_balances) if Venue.SPOT.value in venues else {}
        futures = (
            await self._by_coin(self._client.futures_balances) if venues & _FUTURES_VENUES else {}
        )
        observed_at = self._clock.now()

        readings = []
        for exchange, venue, currency in pools:
            balance = (futures if venue in _FUTURES_VENUES else spot).get(currency)
            readings.append(
                PoolBalanceReading(
                    exchange=exchange,
                    venue=venue,
                    settlement_currency=currency,
                    total=_total(balance),
                    available=_available(balance),
                    observed_at=observed_at,
                )
            )
        return readings

    @staticmethod
    async def _by_coin(
        read: Callable[[], Awaitable[list[CoinBalance]]],
    ) -> dict[str, CoinBalance]:
        return {balance.coin: balance for balance in await read()}


def _total(balance: CoinBalance | None) -> Decimal:
    """``free + frozen - debts``: what the wallet holds, committed or not.

    Frozen capital belongs to the pool even though it cannot be granted
    again, so it counts toward the sizing base while staying out of
    availability. Whether Pionex moves an isolated position's margin into
    ``frozen`` or out of the wallet entirely has not been verified live;
    Pionex cannot place futures orders over the API (CLAUDE.md, settled
    2026-08-26), so no Pionex futures pool is sized from this today.
    """
    if balance is None:
        return Decimal(0)
    total = balance.free + balance.frozen - (balance.debts or Decimal(0))
    return max(total, Decimal(0))


def _available(balance: CoinBalance | None) -> Decimal:
    """Turns one coin's wallet entry into the capital a pool may draw on.

    Three deliberate choices, all erring the same way:

    ``free`` only, never ``free + frozen``. Frozen capital is already
    committed to a live exchange order. Counting it would let the allocator
    hand out money that is spoken for.

    ``debts`` subtracted where the wallet reports it. A cross-margin balance
    financed by borrowing is not capital this system owns. This has only been
    observed as zero on a live account, so treat it as the conservative
    reading rather than a confirmed one.

    A coin Pionex does not mention reads as zero, not as an error. The live
    account confirmed that the API simply omits coins with no balance, and a
    pool with nothing in it is a pool the allocator skips.
    """
    if balance is None:
        return Decimal(0)
    available = balance.free - (balance.debts or Decimal(0))
    return max(available, Decimal(0))
