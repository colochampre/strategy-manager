"""Order submission and fill lookup against the Bybit V5 API.

The sibling of ``read_client.py``, and the class that CAN move money. Its
read-only twin exists so that everything which only looks at the account never
has to hold one of these — and this one composes that one rather than
duplicating its parsing, because reading is a strict subset of what it needs.

**Fills take one hop here, not two.** Pionex keys its fill endpoint by the
EXCHANGE order id, so every settlement had to resolve ``clientOrderId ->
orderId -> fills``. Bybit's ``/v5/execution/list`` accepts ``orderLinkId``
directly, and the reference states that ``orderId`` and ``orderLinkId`` take
priority over every other filter. So the id this system chose before it ever
spoke to the exchange is the id it can settle by, with nothing in between to
go stale or get lost.

**``orderLinkId`` allows exactly 36 characters, and a UUID4 is exactly 36.**
It fits with nothing to spare. That is asserted rather than assumed, because
the client order id is the only handle that makes an in-flight order
recoverable after a crash, and the day someone prefixes it for readability is
the day orders stop being recoverable.

**An empty fill list does not mean the order failed.** It means either "not
published yet" or "never placed", and those lead to opposite decisions. So
existence is a separate question, asked of the order endpoints, and only a
venue that positively reports no such order produces ``BybitOrderNotFound``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import httpx

from strategy_manager.shared.infrastructure.bybit.errors import (
    BybitApiError,
    BybitOrderNotFound,
)
from strategy_manager.shared.infrastructure.bybit.read_client import (
    BybitReadOnlyClient,
    PerpContract,
)
from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner
from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport

CREATE_ORDER_PATH = "/v5/order/create"
OPEN_ORDERS_PATH = "/v5/order/realtime"
ORDER_HISTORY_PATH = "/v5/order/history"
EXECUTIONS_PATH = "/v5/execution/list"

LINEAR = "linear"
MARKET = "Market"

# One-way mode. Bybit's hedge mode uses 1 and 2 for the two sides, and there
# ``reduceOnly`` no longer protects a close — the same trap the Pionex adapter
# refuses a hedged account over.
ONE_WAY_POSITION_IDX: Final = 0

# ``orderLinkId`` accepts at most 36 characters, and str(uuid4()) is exactly
# 36. There is no headroom, so this is a hard check rather than a comment.
ORDER_LINK_ID_MAX_LENGTH: Final = 36
_ORDER_LINK_ID_ALPHABET: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

# Bybit's own code for a lookup that found nothing.
ORDER_NOT_FOUND_CODES: Final = frozenset({"110001"})

# Codes that mean Bybit did NOT evaluate the order: server errors, timeouts,
# rate limits and timestamp-window rejections. Everything else carrying a
# retCode is a decision the exchange made about this order.
#
# The asymmetry is deliberate and it is the same one the Pionex adapter
# documents: a definitive rejection read as ambiguous merely retries, while an
# ambiguous failure read as definitive releases the capital behind a position
# that may well be open.
AMBIGUOUS_CODES: Final = frozenset(
    {
        "10000",  # Server Timeout
        "10002",  # The request time exceeds the time window range
        "10006",  # Too many visits. Exceeded the API Rate Limit
        "10016",  # Server error
        "10018",  # Exceeded the IP Rate Limit
    }
)


@dataclass(frozen=True, slots=True)
class BybitOrderAck:
    """What Bybit returns when it accepts an order: two ids and nothing about
    what it filled at."""

    order_id: str
    order_link_id: str


@dataclass(frozen=True, slots=True)
class BybitExecution:
    """One fill, a straight transcription of the wire payload."""

    exec_id: str
    order_id: str
    order_link_id: str
    symbol: str
    side: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    fee_currency: str
    exec_time_ms: int


class BybitPerpCatalog:
    """Fetches the linear contract table once and answers from memory.

    Cached per instance, and the trade client is built per job, so this costs
    one extra GET on a job that is about to place an order. That is the right
    trade for numbers that decide whether the order is accepted at all: a
    stale cached step produces a rejection nobody can explain from the logs.
    """

    def __init__(self, reader: BybitReadOnlyClient) -> None:
        self._reader = reader
        self._contracts: dict[str, PerpContract] | None = None

    async def rules_for(self, symbol: str) -> PerpContract:
        if self._contracts is None:
            self._contracts = {
                contract.symbol: contract
                for contract in await self._reader.perp_contracts()
            }

        contract = self._contracts.get(symbol.upper())
        if contract is None:
            raise BybitApiError(
                f"Bybit does not list {symbol!r} as a linear contract"
            )
        return contract


class BybitTradeClient:
    """Signed access to the Bybit V5 trade endpoints. This class CAN move
    money."""

    def __init__(self, http: httpx.AsyncClient, signer: BybitSigner) -> None:
        self._transport = BybitTransport(http, signer)
        self._read = BybitReadOnlyClient(http, signer)
        self._symbols = BybitPerpCatalog(self._read)

    async def perp_rules(self, symbol: str) -> PerpContract:
        """The step, minimums and contract type this market imposes."""
        return await self._symbols.rules_for(symbol)

    async def leverage_for(self, symbol: str) -> Decimal:
        """The leverage this symbol is configured at, which is what sizes an
        opening order.

        Read rather than assumed, and never defaulted: a default would
        silently size a position at the wrong multiple of the capital the
        allocation engine granted.
        """
        return await self._read.leverage_for(symbol)

    async def place_market_order(
        self,
        *,
        symbol: str,
        order_link_id: str,
        side: str,
        qty: Decimal,
        reduce_only: bool,
    ) -> BybitOrderAck:
        """Places a market order for ``qty`` of the base coin.

        ``positionIdx`` is pinned to one-way mode. In hedge mode a symbol
        holds a long AND a short at once and ``reduceOnly`` stops protecting a
        close, so an adapter written for one-way must not silently place
        orders against a hedged account.
        """
        _assert_valid_order_link_id(order_link_id)
        if qty <= 0:
            raise BybitApiError(f"qty must be positive, got {qty}")

        payload: dict[str, Any] = {
            "category": LINEAR,
            "symbol": symbol,
            "side": side,
            "orderType": MARKET,
            "qty": _plain(qty),
            "orderLinkId": order_link_id,
            "positionIdx": ONE_WAY_POSITION_IDX,
            "reduceOnly": reduce_only,
        }
        data = await self._transport.post(CREATE_ORDER_PATH, payload)

        if not isinstance(data, dict):
            raise BybitApiError("new order returned no result object")

        order_id = data.get("orderId")
        if not order_id:
            raise BybitApiError("new order returned no orderId")

        # Bybit echoes the client order id back. If it ever echoes a different
        # one, the handle this system uses to recover the order does not name
        # the order Bybit actually created, and settlement would go looking
        # for something that is not there.
        echoed = data.get("orderLinkId")
        if echoed and str(echoed) != order_link_id:
            raise BybitApiError(
                f"Bybit echoed order link id {echoed!r} for an order placed as "
                f"{order_link_id!r}; the order cannot be tracked by our own id"
            )

        return BybitOrderAck(order_id=str(order_id), order_link_id=order_link_id)

    async def fills_for(self, order_link_id: str) -> list[BybitExecution]:
        """Every fill for one of our own order ids, in a single call.

        An empty list is a legitimate transient state — accepted but not yet
        published — and is NOT evidence that the order does not exist. Ask
        ``order_exists`` for that.
        """
        data = await self._read_result(
            EXECUTIONS_PATH, {"category": LINEAR, "orderLinkId": order_link_id}
        )
        return [_parse_execution(entry) for entry in _list_of(data, "list")]

    async def order_exists(self, order_link_id: str) -> bool:
        """Whether Bybit has any record of this order.

        Two endpoints, because they cover different windows: ``realtime``
        holds open and recently-closed orders, ``history`` holds the rest.
        Settlement runs seconds after placement, so the first normally
        answers — but an order that filled and aged out would look like an
        order that never existed if only the first were asked, and that
        mistake releases the capital behind a live position.
        """
        for path in (OPEN_ORDERS_PATH, ORDER_HISTORY_PATH):
            data = await self._read_result(
                path, {"category": LINEAR, "orderLinkId": order_link_id}
            )
            if _list_of(data, "list"):
                return True
        return False

    async def assert_order_placed(self, order_link_id: str) -> None:
        """Raises ``BybitOrderNotFound`` only when Bybit positively reports no
        such order."""
        try:
            found = await self.order_exists(order_link_id)
        except BybitApiError as exc:
            if exc.code in ORDER_NOT_FOUND_CODES:
                raise BybitOrderNotFound(
                    f"Bybit has no order under order link id {order_link_id}"
                ) from exc
            raise

        if not found:
            raise BybitOrderNotFound(
                f"Bybit has no order under order link id {order_link_id}"
            )

    async def _read_result(
        self, path: str, params: Mapping[str, str]
    ) -> Mapping[str, Any]:
        data = await self._transport.get(path, params)
        if not isinstance(data, dict):
            raise BybitApiError(
                f"GET {path} returned no result object, got {type(data).__name__}"
            )
        return data


def _plain(value: Decimal) -> str:
    """Formats a ``Decimal`` without scientific notation.

    ``str(Decimal("1E-8"))`` is ``'1E-8'``, and a size that came out of a
    division very much can carry that exponent. A futures size is ALWAYS a
    quotient (``granted * leverage / price``), so this is on the hot path
    rather than an edge case.
    """
    return format(value.normalize(), "f")


def _assert_valid_order_link_id(order_link_id: str) -> None:
    if not order_link_id or len(order_link_id) > ORDER_LINK_ID_MAX_LENGTH:
        raise BybitApiError(
            f"orderLinkId must be 1-{ORDER_LINK_ID_MAX_LENGTH} characters, got "
            f"{len(order_link_id)}. A UUID4 is exactly {ORDER_LINK_ID_MAX_LENGTH}, "
            "so there is no room for a prefix."
        )
    if not set(order_link_id) <= _ORDER_LINK_ID_ALPHABET:
        raise BybitApiError(
            "orderLinkId must contain only letters, numbers, dashes and underscores"
        )


def _list_of(data: Mapping[str, Any], field: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise BybitApiError(
            f"expected {field!r} to be a list, got {type(value).__name__}; "
            f"payload keys were {sorted(data)}"
        )
    return value


def _parse_execution(entry: Any) -> BybitExecution:
    fields = _object(entry, "execution")
    return BybitExecution(
        exec_id=_text(fields, "execId"),
        order_id=_text(fields, "orderId"),
        order_link_id=str(fields.get("orderLinkId") or ""),
        symbol=_text(fields, "symbol"),
        side=_text(fields, "side"),
        price=_amount(fields, "execPrice"),
        qty=_amount(fields, "execQty"),
        fee=_amount(fields, "execFee"),
        fee_currency=_text(fields, "feeCurrency"),
        exec_time_ms=_millis(fields, "execTime"),
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


def _amount(fields: Mapping[str, Any], field: str) -> Decimal:
    """A JSON number has already lost precision before it reaches this
    process, so it is rejected rather than coerced. This is a fill price: it
    lands in the append-only ledger and can never be corrected there."""
    value = fields.get(field)
    if not isinstance(value, str):
        raise BybitApiError(
            f"{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except ArithmeticError as exc:
        raise BybitApiError(f"{field} is not a valid decimal: {value!r}") from exc


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
