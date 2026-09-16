"""Signed, read-only access to Binance USDⓈ-M futures account state.

Only the per-ASSET figures are exposed, never the account-level totals. In
Multi-Assets Mode those totals are USD-denominated and collateral is shared
across USDT and USDC contracts, which would silently convert a settlement
currency into dollars (CLAUDE.md rule 7). The per-asset fields stay in the
asset's own units either way, so a reader built on them is correct in both
modes.

Field meanings verified live on 2026-09-15 with a position open:

    walletBalance      what the wallet holds, including the margin committed
                       to an open isolated position. Excludes unrealized PnL.
    availableBalance   walletBalance minus the margin actually moved into
                       positions -- exactly, to the cent.
    marginBalance      walletBalance plus unrealized PnL. NOT the pool's
                       total: sizing from it would grow the next position out
                       of gains that have not been realized.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.signer import BinanceSigner
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport

ACCOUNT_PATH = "/fapi/v3/account"


@dataclass(frozen=True, slots=True)
class FuturesAssetBalance:
    """One asset in the USDⓈ-M futures wallet, in that asset's own units."""

    asset: str
    wallet_balance: Decimal
    available_balance: Decimal
    unrealized_profit: Decimal
    position_initial_margin: Decimal
    open_order_initial_margin: Decimal

    @property
    def total(self) -> Decimal:
        """What the pool holds, committed or not.

        Margin behind an open position stays in ``walletBalance``, so a second
        strategy sizes from the same base as the first. Floored at zero.
        """
        return max(self.wallet_balance, Decimal(0))

    @property
    def available(self) -> Decimal:
        """What is still free to commit.

        ``availableBalance`` is the venue's own answer and it was exact on a
        live isolated position: wallet minus the margin actually moved into
        it. It is capped at the total because in CROSS mode Binance can fold
        unrealized profit into it, and a pool whose availability exceeded its
        total would violate the snapshot's own CHECK -- unverified territory,
        so the cap is the conservative reading rather than a claim about it.
        """
        return max(min(self.available_balance, self.total), Decimal(0))


class BinanceReadOnlyClient:
    """Read-only USDⓈ-M futures account state."""

    def __init__(self, http: httpx.AsyncClient, signer: BinanceSigner) -> None:
        self._transport = BinanceTransport(http, signer)

    async def futures_assets(self) -> list[FuturesAssetBalance]:
        """Every asset the futures account reports, funded or not."""
        payload = await self._transport.get_signed(ACCOUNT_PATH)
        if not isinstance(payload, dict):
            raise BinanceApiError(f"{ACCOUNT_PATH} returned a non-object body")

        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise BinanceApiError(f"{ACCOUNT_PATH} returned no 'assets' list")

        return [_parse_asset(entry) for entry in assets]


def _parse_asset(entry: Any) -> FuturesAssetBalance:
    if not isinstance(entry, dict):
        raise BinanceApiError("an entry of 'assets' is not an object")

    asset = entry.get("asset")
    if not isinstance(asset, str) or not asset:
        raise BinanceApiError("an entry of 'assets' has no 'asset' name")

    return FuturesAssetBalance(
        asset=asset,
        wallet_balance=_amount(entry, "walletBalance"),
        available_balance=_amount(entry, "availableBalance"),
        unrealized_profit=_amount(entry, "unrealizedProfit"),
        position_initial_margin=_amount(entry, "positionInitialMargin"),
        open_order_initial_margin=_amount(entry, "openOrderInitialMargin"),
    )


def _amount(fields: Mapping[str, Any], name: str) -> Decimal:
    """Binance sends every amount as a decimal STRING.

    Parsed through ``Decimal`` rather than ``float`` so 642.02828208 stays
    that number: a float would round it, and the rounding would land in a
    position size.
    """
    raw = fields.get(name)
    if raw is None:
        raise BinanceApiError(f"missing {name!r} on asset {fields.get('asset')!r}")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise BinanceApiError(
            f"{name!r} on asset {fields.get('asset')!r} is not a number: {raw!r}"
        ) from exc
