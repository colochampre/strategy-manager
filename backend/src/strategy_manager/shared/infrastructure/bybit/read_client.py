"""Read-only Bybit V5 adapter.

GET-only by construction, for the same reason its Pionex twin is: the
guarantee that this cannot move money is the absence of the code, not a flag.

What it reads maps one-for-one onto the decisions the futures adapter already
makes, which is the point of reading it before writing anything:

``perp_contracts``   Which linear perpetuals exist, at what step and minimum,
                     and in which settlement currency. Bybit's
                     ``lotSizeFilter`` is the direct analogue of Pionex's
                     ``baseStep`` / ``minSizeMarket`` / ``maxSizeMarket``, and
                     ``qty`` for a USDT perpetual is denominated in the BASE
                     coin — the same denomination ``FuturesMarketOrder``
                     already carries.
``wallet_balance``   The margin available to a pool.
``positions``        The live position read model, signed by direction, which
                     is what a close is sized from.
``leverage_for``     Read off the position record: Bybit reports leverage per
                     symbol there rather than on a dedicated endpoint.

**``contractType`` is checked, not assumed.** Bybit lists ``LinearPerpetual``
alongside ``LinearFutures`` (dated, expiring) under the same ``linear``
category. An expiring contract that looked like a perpetual would be traded
as one and then settle underneath the position. Pionex taught the general
lesson — the documented field name was wrong there — so here the value is
read and reported rather than filtered on faith.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner
from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport

INSTRUMENTS_PATH = "/v5/market/instruments-info"
TICKERS_PATH = "/v5/market/tickers"
WALLET_BALANCE_PATH = "/v5/account/wallet-balance"
POSITIONS_PATH = "/v5/position/list"
ACCOUNT_INFO_PATH = "/v5/account/info"
API_KEY_INFO_PATH = "/v5/user/query-api"

LINEAR = "linear"
UNIFIED = "UNIFIED"

LINEAR_PERPETUAL = "LinearPerpetual"


@dataclass(frozen=True, slots=True)
class PerpContract:
    """One linear contract's trading rules, as Bybit reports them.

    A transport read model: a straight transcription of the wire payload, so
    that mapping it onto a capital pool stays a separate, testable decision.
    """

    symbol: str
    contract_type: str
    base_coin: str
    quote_coin: str
    settle_coin: str
    status: str
    qty_step: Decimal
    min_order_qty: Decimal
    max_order_qty: Decimal
    min_notional: Decimal | None
    tick_size: Decimal
    max_leverage: Decimal

    @property
    def is_perpetual(self) -> bool:
        """Dated futures share the ``linear`` category and expire underneath
        any position held in them."""
        return self.contract_type == LINEAR_PERPETUAL

    @property
    def is_usdt_settled(self) -> bool:
        return self.settle_coin.upper() == "USDT"

    @property
    def is_trading(self) -> bool:
        return self.status.upper() == "TRADING"


@dataclass(frozen=True, slots=True)
class CoinBalance:
    """One coin's balance in the unified account."""

    coin: str
    wallet_balance: Decimal
    available_to_withdraw: Decimal | None
    equity: Decimal | None


@dataclass(frozen=True, slots=True)
class Position:
    """One open position exactly as the venue reports it.

    ``side`` is ``Buy``/``Sell``/``` ``` (empty when flat) and ``size`` is
    unsigned, so BOTH are kept: the direction lives in ``side`` here, unlike
    Pionex where it lives in the sign of ``netSize``. Deriving one from the
    other is how a close ends up doubling a position.
    """

    symbol: str
    side: str
    size: Decimal
    avg_price: Decimal
    leverage: Decimal
    position_idx: int
    unrealised_pnl: Decimal | None
    liq_price: Decimal | None

    @property
    def signed_size(self) -> Decimal:
        """The project's own convention: positive long, negative short.

        Translated here rather than anywhere downstream, so the ledger and
        the close-sizing rule keep one meaning of "a position" across venues.
        """
        return -self.size if self.side.upper() == "SELL" else self.size


class BybitReadOnlyClient:
    """Signed, read-only access to Bybit V5 market and account state."""

    def __init__(self, http: httpx.AsyncClient, signer: BybitSigner) -> None:
        self._transport = BybitTransport(http, signer)

    async def perp_contracts(self, limit: int = 1000) -> list[PerpContract]:
        """Every linear contract Bybit lists, perpetual or not.

        Filtering happens at the call site so a dated future is visible as
        something that was deliberately excluded rather than silently absent.
        """
        data = await self._read(
            INSTRUMENTS_PATH, {"category": LINEAR, "limit": str(limit)}
        )
        return [_parse_contract(entry) for entry in _list_of(data, "list")]

    async def last_price(self, symbol: str) -> Decimal:
        data = await self._read(TICKERS_PATH, {"category": LINEAR, "symbol": symbol})
        tickers = _list_of(data, "list")
        if not tickers:
            raise BybitApiError(f"Bybit reports no ticker for {symbol!r}")
        return _amount(_object(tickers[0], "ticker"), "lastPrice")

    async def wallet_balance(self) -> list[CoinBalance]:
        """Unified-account balances. Bybit nests them one level deeper than
        Pionex: ``result.list[0].coin[]``."""
        data = await self._read(WALLET_BALANCE_PATH, {"accountType": UNIFIED})
        accounts = _list_of(data, "list")
        if not accounts:
            return []
        return [
            _parse_balance(entry)
            for entry in _list_of(_object(accounts[0], "account"), "coin")
        ]

    async def positions(self, settle_coin: str = "USDT") -> list[Position]:
        """Open positions. Bybit requires a filter, so the settlement currency
        is it — which happens to be exactly how this system pools capital."""
        data = await self._read(
            POSITIONS_PATH, {"category": LINEAR, "settleCoin": settle_coin}
        )
        return [_parse_position(entry) for entry in _list_of(data, "list")]

    async def leverage_for(self, symbol: str) -> Decimal:
        """Bybit reports leverage on the POSITION record rather than on a
        dedicated endpoint, and it does so even when the position is flat.

        Matched by symbol rather than taken positionally, for the reason
        Pionex made expensive: a list keyed by nothing is where the wrong
        market's leverage gets read as this one's.
        """
        data = await self._read(
            POSITIONS_PATH, {"category": LINEAR, "symbol": symbol}
        )
        for entry in _list_of(data, "list"):
            fields = _object(entry, "position")
            if _text(fields, "symbol").upper() == symbol.upper():
                return _amount(fields, "leverage")
        raise BybitApiError(f"Bybit reports no leverage for {symbol!r}")

    async def api_key_info(self) -> Mapping[str, Any]:
        """What this key is actually allowed to do, and for how long.

        Read-only, and the most useful call this client makes before anything
        is sealed into the vault: it reports ``readOnly``, the granted
        ``permissions`` (including ``Wallet.Withdraw``), the bound ``ips``,
        and — only for keys with no IP binding — ``expiredAt`` and
        ``deadlineDay``.

        Verbatim rather than parsed, because it is consumed by a script whose
        job is to show the operator what they are about to store.
        """
        return await self._read(API_KEY_INFO_PATH)

    async def account_info(self) -> Mapping[str, Any]:
        """Margin mode and account type, verbatim. Unparsed on purpose: this
        is the read whose shape is least certain, and a probe should show what
        arrived rather than what was expected.
        """
        return await self._read(ACCOUNT_INFO_PATH)

    async def _read(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        data = await self._transport.get(path, params)
        if not isinstance(data, dict):
            raise BybitApiError(
                f"GET {path} returned no result object, got {type(data).__name__}"
            )
        return data


def _list_of(data: Mapping[str, Any], field: str) -> list[Any]:
    """Reads a list field, naming what actually arrived when it is not one.

    The observed keys are in the message on purpose: a probe's whole job is
    finding where the documented shape and the live shape disagree, and
    "list is not a list" says nothing about what came instead.
    """
    value = data.get(field)
    if not isinstance(value, list):
        raise BybitApiError(
            f"expected {field!r} to be a list, got {type(value).__name__}; "
            f"payload keys were {sorted(data)}"
        )
    return value


def _parse_contract(entry: Any) -> PerpContract:
    fields = _object(entry, "instrument")
    lot = _object(fields.get("lotSizeFilter"), "lotSizeFilter")
    price = _object(fields.get("priceFilter"), "priceFilter")
    leverage = _object(fields.get("leverageFilter"), "leverageFilter")

    return PerpContract(
        symbol=_text(fields, "symbol").upper(),
        contract_type=_text(fields, "contractType"),
        base_coin=_text(fields, "baseCoin"),
        quote_coin=_text(fields, "quoteCoin"),
        settle_coin=_text(fields, "settleCoin"),
        status=_text(fields, "status"),
        qty_step=_amount(lot, "qtyStep"),
        min_order_qty=_amount(lot, "minOrderQty"),
        max_order_qty=_amount(lot, "maxOrderQty"),
        min_notional=_optional_amount(lot, "minNotionalValue"),
        tick_size=_amount(price, "tickSize"),
        max_leverage=_amount(leverage, "maxLeverage"),
    )


def _parse_balance(entry: Any) -> CoinBalance:
    fields = _object(entry, "coin balance")
    return CoinBalance(
        coin=_text(fields, "coin"),
        wallet_balance=_amount(fields, "walletBalance"),
        available_to_withdraw=_optional_amount(fields, "availableToWithdraw"),
        equity=_optional_amount(fields, "equity"),
    )


def _parse_position(entry: Any) -> Position:
    fields = _object(entry, "position")
    return Position(
        symbol=_text(fields, "symbol").upper(),
        # Flat positions report an empty side, so this one field is allowed to
        # be blank where every other text field is not.
        side=str(fields.get("side") or ""),
        size=_amount(fields, "size"),
        avg_price=_amount_or_zero(fields, "avgPrice"),
        leverage=_amount(fields, "leverage"),
        position_idx=_integer(fields, "positionIdx"),
        unrealised_pnl=_optional_amount(fields, "unrealisedPnl"),
        liq_price=_optional_amount(fields, "liqPrice"),
    )


def _object(entry: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise BybitApiError(f"{label} is not an object, got {type(entry).__name__}")
    return entry


def _text(fields: Mapping[str, Any], field: str) -> str:
    value = fields.get(field)
    if not isinstance(value, str) or not value:
        raise BybitApiError(f"{field} must be a non-empty string, got {value!r}")
    return value


def _integer(fields: Mapping[str, Any], field: str) -> int:
    value = fields.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BybitApiError(
            f"{field} must be an integer, got {type(value).__name__}"
        )
    return value


def _amount(fields: Mapping[str, Any], field: str) -> Decimal:
    """Amounts arrive as strings and are parsed exactly.

    A JSON number has already lost precision before it reaches this process,
    so it is rejected rather than coerced. Same rule as every other venue
    adapter here, and for the same reason: this is real money.
    """
    value = fields.get(field)
    if not isinstance(value, str):
        raise BybitApiError(
            f"{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise BybitApiError(f"{field} is not a valid decimal: {value!r}") from exc


def _amount_or_zero(fields: Mapping[str, Any], field: str) -> Decimal:
    """Bybit sends an empty string for a price that does not apply to a flat
    position. That is 'no price', and zero is the honest reading of it here —
    unlike a missing PnL, which is 'not reported' and must stay None."""
    return Decimal(0) if fields.get(field) == "" else _amount(fields, field)


def _optional_amount(fields: Mapping[str, Any], field: str) -> Decimal | None:
    """``None`` means "not reported", never zero.

    Bybit uses an empty string for both "absent" and "not applicable", so both
    collapse to None here — an unreported liquidation price and one of zero
    are very different facts and must not be confused.
    """
    value = fields.get(field)
    return None if value is None or value == "" else _amount(fields, field)
