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
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Final

import httpx

from strategy_manager.shared.infrastructure.bybit.errors import (
    BybitApiError,
    BybitRuleRefusal,
)
from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner
from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport

INSTRUMENTS_PATH = "/v5/market/instruments-info"
TICKERS_PATH = "/v5/market/tickers"
WALLET_BALANCE_PATH = "/v5/account/wallet-balance"
POSITIONS_PATH = "/v5/position/list"
ACCOUNT_INFO_PATH = "/v5/account/info"
API_KEY_INFO_PATH = "/v5/user/query-api"
ACCOUNT_COINS_BALANCE_PATH = "/v5/asset/transfer/query-account-coins-balance"

# Same wire path as ``trade_client.py``'s ``EXECUTIONS_PATH``, redeclared
# here rather than imported: ``trade_client`` imports THIS module (reading
# is a strict subset of what it needs), and this module has no reason to
# import back the other way.
EXECUTIONS_WINDOW_PATH = "/v5/execution/list"

LINEAR = "linear"
UNIFIED = "UNIFIED"

_EPOCH = datetime.fromtimestamp(0, UTC)

# Execution types that represent a genuine position change and are safe to
# book. ``Funding`` is charged periodically on an open position and is not a
# fill at all -- booking it as one would record a close that never happened.
_TRADE_EXEC_TYPES: Final = frozenset({"Trade", "BustTrade", "AdlTrade"})
_FUNDING_EXEC_TYPE: Final = "Funding"

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

    def round_qty(self, qty: Decimal) -> Decimal:
        """Truncates to the venue's step, downward.

        Always DOWN, for the reason every venue adapter here repeats: rounding
        up spends capital the allocation engine never granted, and on a close
        asks the venue to reduce more than the position holds. Down leaves
        dust; up invents money.
        """
        if self.qty_step <= 0:
            return qty
        steps = (qty / self.qty_step).to_integral_value(rounding=ROUND_DOWN)
        return steps * self.qty_step

    def assert_tradable(self, qty: Decimal, price: Decimal | None) -> None:
        """Every constraint that decides whether this order is placeable.

        Named individually because the operator's remedy differs for each: a
        qty below the floor needs a bigger grant, one above the ceiling needs
        a smaller one or less leverage, a dated contract needs a different
        symbol, and an untradable one needs a different market entirely.

        ``price`` is ``None`` when the caller has none — a close is sized from
        the ledger, not from an amount and a price — and the notional check is
        then skipped rather than run against an invented number.
        """
        if not self.is_perpetual:
            raise BybitRuleRefusal(
                f"{self.symbol} is a {self.contract_type}, not a perpetual; it "
                "expires underneath any position held in it"
            )
        if not self.is_trading:
            raise BybitRuleRefusal(
                f"{self.symbol} is {self.status}, not Trading; it cannot be traded"
            )
        if qty < self.min_order_qty:
            raise BybitRuleRefusal(
                f"{self.symbol} requires an order of at least {self.min_order_qty} "
                f"{self.base_coin}; this one is {qty}"
            )
        if qty > self.max_order_qty:
            raise BybitRuleRefusal(
                f"{self.symbol} caps an order at {self.max_order_qty} "
                f"{self.base_coin}; this one is {qty}"
            )

        if price is None or self.min_notional is None:
            return

        notional = qty * price
        if notional < self.min_notional:
            raise BybitRuleRefusal(
                f"{self.symbol} requires a notional of at least "
                f"{self.min_notional}; this one is {notional} ({qty} at {price})"
            )


@dataclass(frozen=True, slots=True)
class CoinBalance:
    """One coin's balance in the unified account."""

    coin: str
    wallet_balance: Decimal
    available_to_withdraw: Decimal | None
    equity: Decimal | None


@dataclass(frozen=True, slots=True)
class UnifiedCoinBalance:
    """One coin in the unified account, with the fields that decide what a
    pool may allocate.

    **Not ``totalEquity``, and not ``usdValue``.** Both are USD valuations —
    on a 5 USDT balance the account reported ``4.99968`` — so reading either
    would silently convert a settlement-currency amount into dollars, against
    CLAUDE.md rule 7. Availability is computed in the coin's own units.

    **Not ``availableToWithdraw`` either.** Bybit returns it EMPTY on this
    account, and an empty string that reads like a zero is how a pool reports
    capital it does not have.
    """

    coin: str
    wallet_balance: Decimal
    total_position_im: Decimal
    total_order_im: Decimal
    locked: Decimal
    equity: Decimal | None
    usd_value: Decimal | None
    is_collateral: bool

    @property
    def available(self) -> Decimal:
        """What a pool may draw on, in this coin's own units.

        Initial margin already committed to positions and to resting orders
        is subtracted, and so is anything locked. All three are capital that
        is spoken for; counting them would let the allocator hand out money
        twice — the same error, on one venue, that configuring two pools over
        one unified balance would make across venues.

        Floored at zero: a negative available balance is not a debt this
        system can act on, and handing a negative number to the allocation
        engine would be worse than reporting nothing.
        """
        committed = self.total_position_im + self.total_order_im + self.locked
        return max(self.wallet_balance - committed, Decimal(0))


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


@dataclass(frozen=True, slots=True)
class BybitWindowExecution:
    """One execution from a WINDOW fetch (``/v5/execution/list`` filtered by
    time range, not by order) — a straight transcription of the wire
    payload, side and business-rule translation left to the reader that
    consumes it (``BybitVenueFillReader``, ``reconciliation/infrastructure``).

    Unlike ``trade_client.BybitExecution``, ``order_id`` is optional: an
    order-scoped fetch's caller already resolved the order by id, so an
    order id is guaranteed there. A window fetch has no order at all, so
    this parser stays tolerant of a missing one (design decision 4) — the
    order-scoped ``_parse_execution`` in ``trade_client.py`` is untouched
    and still requires it.
    """

    exec_id: str
    order_id: str | None
    symbol: str
    side: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    fee_currency: str
    exec_time_ms: int
    exec_type: str


class BybitReadOnlyClient:
    """Signed, read-only access to Bybit V5 market and account state."""

    def __init__(self, http: httpx.AsyncClient, signer: BybitSigner) -> None:
        self._transport = BybitTransport(http, signer)

    async def fills_in_window(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        page_limit: int,
        max_pages: int,
    ) -> list[BybitWindowExecution]:
        """Every trade-type execution for ``symbol`` in ``[start, end]``,
        paginated on ``nextPageCursor`` while it is non-empty.

        Bounded by ``max_pages``: silently truncating a fill list would
        under-book a close, which is worse than refusing outright (design
        decision 9), so the bound RAISES rather than stopping quietly.

        ``Funding`` executions are filtered out here — a funding charge is
        not a position change. Any OTHER execution type is neither a known
        trade type nor ``Funding``, and is refused by name rather than
        silently skipped or silently included, because guessing which one
        it is risks under- or over-booking a close.
        """
        executions: list[BybitWindowExecution] = []
        cursor = ""
        for _ in range(max_pages):
            params = {
                "category": LINEAR,
                "symbol": symbol,
                "startTime": str(_to_millis(start)),
                "endTime": str(_to_millis(end)),
                "limit": str(page_limit),
            }
            if cursor:
                params["cursor"] = cursor
            data = await self._read(EXECUTIONS_WINDOW_PATH, params)
            for entry in _list_of(data, "list"):
                execution = _parse_window_execution(entry)
                if execution.exec_type == _FUNDING_EXEC_TYPE:
                    continue
                if execution.exec_type not in _TRADE_EXEC_TYPES:
                    raise BybitApiError(
                        f"Bybit execution {execution.exec_id} on {symbol} has "
                        f"unrecognised execType {execution.exec_type!r}; it is "
                        "neither a known trade type nor Funding, and booking "
                        "it blind risks under- or over-booking a close"
                    )
                executions.append(execution)
            cursor = str(data.get("nextPageCursor") or "")
            if not cursor:
                return executions

        raise BybitApiError(
            f"Bybit fill window for {symbol} did not end within {max_pages} "
            f"pages of {page_limit}; truncating here risks under-booking a "
            "close"
        )

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

    async def account_coins_balance(
        self, account_type: str, coins: str
    ) -> list[CoinBalance]:
        """Balances of one specific account type.

        Bybit splits money across account types — ``FUND`` is where a deposit
        lands, ``UNIFIED`` is where trading collateral lives — and they are
        not the same pot. Reading only ``UNIFIED`` reports zero for an account
        that has just been funded, which looks exactly like an account with no
        money in it.
        """
        data = await self._read(
            ACCOUNT_COINS_BALANCE_PATH, {"accountType": account_type, "coin": coins}
        )
        return [_parse_transfer_balance(entry) for entry in _list_of(data, "balance")]

    async def unified_balances(self) -> list[UnifiedCoinBalance]:
        """Every coin in the unified account, with its availability fields.

        This is the read a capital pool is sized from. There is exactly one
        unified balance per coin — Bybit pools collateral across products —
        so two pools over the same settlement currency would be two views of
        one pot, which is why ``BybitBalanceReader`` refuses to serve them.
        """
        account = await self.unified_account_raw()
        if not account:
            return []
        return [
            _parse_unified_balance(entry) for entry in _list_of(account, "coin")
        ]

    async def unified_account_raw(self) -> Mapping[str, Any]:
        """The unified account object verbatim, account-level totals included.

        Unparsed on purpose: the account-level equity fields are what answer
        whether this account pools collateral across products, and a probe
        should show what arrived rather than what was expected.
        """
        data = await self._read(WALLET_BALANCE_PATH, {"accountType": UNIFIED})
        accounts = _list_of(data, "list")
        return _object(accounts[0], "account") if accounts else {}

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


def _parse_unified_balance(entry: Any) -> UnifiedCoinBalance:
    """Margin fields default to zero when absent.

    That is safe in one direction only, and it is the right one: a missing
    ``totalPositionIM`` read as zero makes availability look LARGER than it
    is, which is exactly backwards. So they are parsed strictly when present
    and default to zero only when the key is absent entirely — Bybit sends
    "0" for an account with no positions, so an absent key means a shape
    change worth noticing rather than a quiet zero.
    """
    fields = _object(entry, "unified coin balance")
    return UnifiedCoinBalance(
        coin=_text(fields, "coin"),
        wallet_balance=_amount(fields, "walletBalance"),
        total_position_im=_amount_or_zero(fields, "totalPositionIM"),
        total_order_im=_amount_or_zero(fields, "totalOrderIM"),
        locked=_amount_or_zero(fields, "locked"),
        equity=_optional_amount(fields, "equity"),
        usd_value=_optional_amount(fields, "usdValue"),
        is_collateral=bool(fields.get("collateralSwitch")),
    )


def _parse_transfer_balance(entry: Any) -> CoinBalance:
    """The asset endpoint reports ``transferBalance`` where the wallet
    endpoint reports ``equity``. Different names, different meanings: one is
    what can be moved between account types, the other is what backs
    positions. Mapped onto the same read model but not conflated — the field
    that arrives is the field that is used.
    """
    fields = _object(entry, "coin balance")
    return CoinBalance(
        coin=_text(fields, "coin"),
        wallet_balance=_amount(fields, "walletBalance"),
        available_to_withdraw=_optional_amount(fields, "transferBalance"),
        equity=None,
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


def _parse_window_execution(entry: Any) -> BybitWindowExecution:
    """Tolerant of a missing ``orderId`` — the strict, order-scoped
    ``_parse_execution`` in ``trade_client.py`` is a separate function and
    stays untouched, because its caller already resolved the order by id."""
    fields = _object(entry, "execution")
    order_id = fields.get("orderId")
    return BybitWindowExecution(
        exec_id=_text(fields, "execId"),
        order_id=str(order_id) if order_id else None,
        symbol=_text(fields, "symbol"),
        side=_text(fields, "side"),
        price=_amount(fields, "execPrice"),
        qty=_amount(fields, "execQty"),
        fee=_amount(fields, "execFee"),
        fee_currency=_text(fields, "feeCurrency"),
        exec_time_ms=_millis(fields, "execTime"),
        exec_type=_text(fields, "execType"),
    )


def _to_millis(moment: datetime) -> int:
    """Milliseconds since the epoch, by subtraction rather than
    ``timestamp() * 1000`` so no float division stands between a caller's
    instant and the signed query string."""
    delta = moment - _EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _millis(fields: Mapping[str, Any], field: str) -> int:
    """Bybit sends timestamps as STRINGS of milliseconds where Pionex sends
    integers. Accepting both would hide a shape change; this accepts what
    Bybit documents and says so when it is something else."""
    value = fields.get(field)
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise BybitApiError(
            f"{field} must be a millisecond timestamp, got {type(value).__name__}"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise BybitApiError(f"{field} is not a timestamp: {value!r}") from exc


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
