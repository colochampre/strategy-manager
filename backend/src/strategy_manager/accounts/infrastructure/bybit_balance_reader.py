"""Implements ``ExchangeBalanceReaderPort`` over the read-only Bybit client.

**One balance, not one per venue.** Its Pionex twin maps spot pools onto the
spot wallet and futures pools onto the futures wallet, because Pionex keeps
those genuinely separate. Bybit's Unified Trading Account does not: the coin
reports ``collateralSwitch: true``, equity is reported at the account level,
and there is no per-product wallet in the payload at all. One USDT balance
stands behind spot and linear perpetuals together.

So the venue does not select a wallet here — the settlement currency does,
and that is the whole mapping.

**Which is why two pools over one currency are REFUSED.** Configure both
``spot/USDT`` and ``usdt-m/USDT`` against this venue and each would read the
same pot, so the allocation engine could reserve the same money twice — with
every reservation looking perfectly valid on its own. Nothing downstream can
detect that, because from inside a pool the number is correct. It has to be
refused where the two pools are first seen together, which is here.

Failing the balance sync job is the right severity: a pool whose availability
cannot be read stops trading, which is what should happen when the alternative
is over-allocating real capital.
"""

from collections.abc import Sequence
from decimal import Decimal

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.bybit.read_client import (
    BybitReadOnlyClient,
    UnifiedCoinBalance,
)


class BybitBalanceReader:
    """Reads the unified balances backing the configured pools, in one pass."""

    def __init__(self, client: BybitReadOnlyClient, clock: ClockPort) -> None:
        self._client = client
        self._clock = clock

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        """Fetches the unified account once, no matter how many pools draw on
        it.

        ``observed_at`` is stamped once for the whole batch. Every reading
        comes from a single response, so a per-pool timestamp would imply a
        precision that is not there.
        """
        _assert_one_pool_per_currency(pools)

        by_coin = {
            balance.coin.upper(): balance
            for balance in await self._client.unified_balances()
        }
        observed_at = self._clock.now()

        return [
            PoolBalanceReading(
                venue=venue,
                settlement_currency=currency,
                available=_available(by_coin.get(currency.upper())),
                observed_at=observed_at,
            )
            for venue, currency in pools
        ]


def _assert_one_pool_per_currency(pools: Sequence[PoolKey]) -> None:
    """Refuses a configuration where two pools would read the same balance."""
    seen: dict[str, str] = {}
    for venue, currency in pools:
        key = currency.upper()
        first = seen.get(key)
        if first is not None:
            raise InvariantViolation(
                f"pools {first}/{currency} and {venue}/{currency} both read "
                "Bybit's unified balance, which is one pot: collateral is not "
                "segregated by product on this venue. Two pools over it would "
                "let the same money be reserved twice. Enable exactly one pool "
                f"per settlement currency on Bybit (CLAUDE.md rule 5)."
            )
        seen[key] = venue


def _available(balance: UnifiedCoinBalance | None) -> Decimal:
    """A coin the account does not mention reads as zero, not as an error.

    Bybit omits coins with no balance, and a pool with nothing in it is a pool
    the allocator skips — which is a correct outcome, not a failure.
    """
    return Decimal(0) if balance is None else balance.available
