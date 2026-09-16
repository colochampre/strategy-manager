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
from decimal import ROUND_DOWN, Decimal, InvalidOperation
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


EXCHANGE_INFO_PATH = "/fapi/v1/exchangeInfo"
SYMBOL_CONFIG_PATH = "/fapi/v1/symbolConfig"
POSITION_RISK_PATH = "/fapi/v3/positionRisk"

PERPETUAL = "PERPETUAL"


@dataclass(frozen=True, slots=True)
class PerpContract:
    """One USDⓈ-M contract's trading rules, as Binance reports them.

    A transport read model: a straight transcription of the wire payload, so
    mapping it onto an order stays a separate, testable decision.

    ``market_max_qty`` is Binance's own trap. A market order is capped lower
    than a limit order on the same symbol -- on BTCUSDT, 120 against 1000
    (verified 2026-09-15) -- and this system only ever sends market orders, so
    the MARKET_LOT_SIZE ceiling is the one that decides whether an order is
    placeable.
    """

    symbol: str
    contract_type: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    status: str
    qty_step: Decimal
    min_qty: Decimal
    market_max_qty: Decimal
    min_notional: Decimal | None
    tick_size: Decimal

    @property
    def is_perpetual(self) -> bool:
        """Dated quarterlies share this catalogue and expire underneath any
        position held in them.

        ``TRADIFI_PERPETUAL`` is excluded deliberately: 191 of the 897 listed
        contracts carry it (2026-09-15), they are a different product, and
        treating an unrecognised type as tradable is how a position ends up
        somewhere nobody chose.
        """
        return self.contract_type == PERPETUAL

    @property
    def is_trading(self) -> bool:
        return self.status.upper() == "TRADING"

    def round_qty(self, qty: Decimal) -> Decimal:
        """Truncates to the venue's step, downward.

        Always DOWN: rounding up spends capital the allocation engine never
        granted, and on a close asks the venue to reduce more than the
        position holds. Down leaves dust; up invents money.
        """
        if self.qty_step <= 0:
            return qty
        steps = (qty / self.qty_step).to_integral_value(rounding=ROUND_DOWN)
        return steps * self.qty_step

    def assert_tradable(self, qty: Decimal, price: Decimal | None) -> None:
        """Every constraint that decides whether this market order is placeable.

        Named individually because the operator's remedy differs for each: a
        qty below the floor needs a bigger grant, one above the ceiling needs a
        smaller one or less leverage, a dated contract needs a different
        symbol, and a halted one needs a different market entirely.

        ``price`` is ``None`` when the caller has none -- a close is sized from
        the ledger, not from an amount and a price -- and the notional check is
        then skipped rather than run against an invented number.
        """
        if not self.is_perpetual:
            raise BinanceApiError(
                f"{self.symbol} is a {self.contract_type}, not a {PERPETUAL}; it "
                "expires or settles underneath any position held in it"
            )
        if not self.is_trading:
            raise BinanceApiError(
                f"{self.symbol} is {self.status}, not TRADING; it cannot be traded"
            )
        if qty < self.min_qty:
            raise BinanceApiError(
                f"{self.symbol} requires an order of at least {self.min_qty} "
                f"{self.base_asset}; this one is {qty}"
            )
        if qty > self.market_max_qty:
            raise BinanceApiError(
                f"{self.symbol} caps a MARKET order at {self.market_max_qty} "
                f"{self.base_asset} (lower than its limit-order ceiling); this "
                f"one is {qty}"
            )

        if price is None or self.min_notional is None:
            return

        notional = qty * price
        if notional < self.min_notional:
            raise BinanceApiError(
                f"{self.symbol} requires a notional of at least "
                f"{self.min_notional}; this one is {notional} ({qty} at {price})"
            )


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    """What the ACCOUNT is configured to do on one symbol.

    Both fields are account settings the owner can change from Binance's UI,
    so they are read at order-build time and never assumed.
    """

    symbol: str
    leverage: Decimal
    margin_type: str
    is_auto_add_margin: bool


@dataclass(frozen=True, slots=True)
class Position:
    """One position exactly as the venue reports it.

    Binance puts the direction in the SIGN of ``positionAmt`` -- negative is
    short -- where Bybit uses a separate ``side`` field. Translated into this
    project's own convention here, so the ledger and the close-sizing rule keep
    one meaning of "a position" across venues.
    """

    symbol: str
    position_side: str
    signed_size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    notional: Decimal
    unrealized_profit: Decimal
    liquidation_price: Decimal | None

    @property
    def is_open(self) -> bool:
        return self.signed_size != 0


def _parse_contract(entry: Any) -> PerpContract:
    if not isinstance(entry, dict):
        raise BinanceApiError("an entry of 'symbols' is not an object")

    lot = _filter(entry, "LOT_SIZE")
    market_lot = _filter(entry, "MARKET_LOT_SIZE")
    price = _filter(entry, "PRICE_FILTER")
    notional = _filter(entry, "MIN_NOTIONAL")

    return PerpContract(
        symbol=str(entry.get("symbol", "")),
        contract_type=str(entry.get("contractType", "")),
        base_asset=str(entry.get("baseAsset", "")),
        quote_asset=str(entry.get("quoteAsset", "")),
        margin_asset=str(entry.get("marginAsset", "")),
        status=str(entry.get("status", "")),
        qty_step=_amount(lot, "stepSize"),
        min_qty=_amount(lot, "minQty"),
        # The MARKET ceiling, not LOT_SIZE's: this system sends market orders.
        market_max_qty=_amount(market_lot, "maxQty"),
        min_notional=_optional_amount(notional, "notional"),
        tick_size=_amount(price, "tickSize"),
    )


def _filter(entry: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    filters = entry.get("filters")
    if not isinstance(filters, list):
        raise BinanceApiError(f"{entry.get('symbol')!r} reports no filters")
    for candidate in filters:
        if isinstance(candidate, dict) and candidate.get("filterType") == kind:
            return candidate
    raise BinanceApiError(f"{entry.get('symbol')!r} has no {kind} filter")


def _parse_symbol_config(entry: Any) -> SymbolConfig:
    if not isinstance(entry, dict):
        raise BinanceApiError("a symbolConfig entry is not an object")
    return SymbolConfig(
        symbol=str(entry.get("symbol", "")),
        leverage=_amount(entry, "leverage"),
        margin_type=str(entry.get("marginType", "")),
        is_auto_add_margin=bool(entry.get("isAutoAddMargin", False)),
    )


def _parse_position(entry: Any) -> Position:
    if not isinstance(entry, dict):
        raise BinanceApiError("a positionRisk entry is not an object")
    return Position(
        symbol=str(entry.get("symbol", "")),
        position_side=str(entry.get("positionSide", "")),
        signed_size=_amount(entry, "positionAmt"),
        entry_price=_amount(entry, "entryPrice"),
        mark_price=_amount(entry, "markPrice"),
        notional=_amount(entry, "notional"),
        unrealized_profit=_amount(entry, "unRealizedProfit"),
        liquidation_price=_optional_amount(entry, "liquidationPrice"),
    )


def _matching(entries: Any, symbol: str, what: str) -> Mapping[str, Any]:
    """Finds the entry for ``symbol`` in a LIST response.

    Binance answers a single-symbol ``symbolConfig`` query with a one-element
    LIST, not the flat object its documentation shows (verified live
    2026-09-15) -- the same trap Pionex's leverage endpoint set, where taking
    index 0 reads another market's setting. Matching by symbol is the only
    reading that cannot be wrong.
    """
    if not isinstance(entries, list):
        raise BinanceApiError(f"{what} for {symbol} did not return a list")
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("symbol", "")).upper() == symbol.upper():
            return entry
    raise BinanceApiError(f"{what} returned no entry for {symbol}")


class BinanceReadOnlyClient:
    """Read-only USDⓈ-M futures account and market state."""

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

    async def perp_rules(self, symbol: str) -> PerpContract:
        """The one contract's rules. Public: no signature, no account needed.

        The catalogue is fetched whole because Binance offers no per-symbol
        variant of it, and the entry is then matched by symbol rather than
        taken positionally.
        """
        payload = await self._transport.get_public(EXCHANGE_INFO_PATH)
        if not isinstance(payload, dict):
            raise BinanceApiError(f"{EXCHANGE_INFO_PATH} returned a non-object body")
        return _parse_contract(_matching(payload.get("symbols"), symbol, "exchangeInfo"))

    async def symbol_config(self, symbol: str) -> SymbolConfig:
        """The ACCOUNT's leverage and margin type for one symbol."""
        payload = await self._transport.get_signed(
            SYMBOL_CONFIG_PATH, {"symbol": symbol}
        )
        return _parse_symbol_config(_matching(payload, symbol, "symbolConfig"))

    async def leverage_for(self, symbol: str) -> Decimal:
        """The multiple an opening order will actually be sized at.

        Read at order-build time and never defaulted: it is an account setting
        the owner can change from the UI, so the number in force an hour later
        is not necessarily the one that sized a position.
        """
        return (await self.symbol_config(symbol)).leverage

    async def position_for(self, symbol: str) -> Position | None:
        """The open position on one symbol, or ``None`` when flat.

        Flat is reported as an entry with ``positionAmt`` of zero rather than
        an absent one, so "no position" is a value here and not a missing key.
        """
        payload = await self._transport.get_signed(
            POSITION_RISK_PATH, {"symbol": symbol}
        )
        if not isinstance(payload, list):
            raise BinanceApiError(f"{POSITION_RISK_PATH} did not return a list")
        for entry in payload:
            if isinstance(entry, dict) and str(entry.get("symbol", "")).upper() == symbol.upper():
                position = _parse_position(entry)
                return position if position.is_open else None
        return None


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


def _optional_amount(fields: Mapping[str, Any], name: str) -> Decimal | None:
    """A field the venue may omit or send empty.

    An empty string is NOT read as zero: a zero minimum means "no floor" and
    an absent one means "not reported", and confusing the two lets an order
    through a check that never ran.
    """
    raw = fields.get(name)
    if raw is None or raw == "":
        return None
    return _amount(fields, name)
