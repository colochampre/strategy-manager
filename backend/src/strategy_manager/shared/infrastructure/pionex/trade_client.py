"""Order submission and fill lookup against the Pionex spot Trade API.

Endpoints verified 2026-08-20 against
https://pionex-doc.gitbook.io/apidocs/restful/orders/new-order.

**The conditional that matters.** A Pionex spot MARKET order takes a
different parameter depending on its side:

- MARKET BUY  -> ``amount``, in the QUOTE currency
- MARKET SELL -> ``size``,   in the BASE currency

Sending the wrong one is rejected. Rather than branch on a side flag inside
one method, this class exposes ``place_market_buy`` and ``place_market_sell``
separately, so both request shapes are visible in the code instead of hidden
behind an ``if``. The caller already knows which it has: the domain's
``MarketBuy | MarketSell`` decided it.

**Fills need two hops.** Pionex answers a new order with an id and nothing
else, and its fill endpoint is keyed by the EXCHANGE order id, not the client
one. So: ``clientOrderId -> order (yields orderId) -> fills``. Both hops live
here; ``execution``'s ``fetch_fills(client_order_id, symbol)`` expresses the
intent, and this is where the mechanics stay.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx

from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

NEW_ORDER_PATH = "/api/v1/trade/order"
ORDER_BY_CLIENT_ORDER_ID_PATH = "/api/v1/trade/orderByClientOrderId"
FILLS_BY_ORDER_ID_PATH = "/api/v1/trade/fillsByOrderId"

MARKET = "MARKET"
BUY = "BUY"
SELL = "SELL"

# Pionex accepts letters, numbers and hyphens, up to 64 characters. A UUID4
# string is 36 characters of hex and hyphens, so it fits with room to spare --
# but this is asserted rather than assumed, because the client order id is the
# only handle that makes an in-flight order recoverable after a crash.
CLIENT_ORDER_ID_MAX_LENGTH: Final = 64
_CLIENT_ORDER_ID_ALPHABET: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
)

# Rejection codes that mean "this order does not exist", as opposed to "the
# call failed".
#
# VERIFIED 2026-08-21 against the owner's live account via
# ``backend/scripts/check_pionex_order_lookup.py``. Looking up a client order
# id that cannot exist returns, over HTTP 200:
#
#     {"result": false, "code": "TRADE_ORDER_NOT_EXIST", "message": "order not found"}
#
# This set held three plausible-sounding names before that probe ran and every
# one of them was wrong. That is the argument for keeping it to exactly what
# Pionex has been observed to send: a guessed code that happens to be right is
# still a guess, and a guessed code that is wrong makes this system release
# the capital behind a live position. Add an entry only after seeing it come
# back from the API, and match on the code, never the message — messages get
# reworded, codes are the contract.
#
# Anything not listed here is treated as a failed call, which retries. That
# asymmetry is deliberate and is explained on ``PionexOrderNotFound``.
ORDER_NOT_FOUND_CODES: Final = frozenset({"TRADE_ORDER_NOT_EXIST"})


@dataclass(frozen=True, slots=True)
class PionexOrderAck:
    """What Pionex returns when it accepts a new order: an id, and nothing
    about what it filled at."""

    order_id: str
    client_order_id: str


@dataclass(frozen=True, slots=True)
class PionexFill:
    """One fill record, a straight transcription of the wire payload.

    Amounts stay ``Decimal`` parsed from the string Pionex sent. Mapping this
    onto the ledger's own ``Fill`` is a separate, testable decision made in
    ``execution.infrastructure.pionex_exchange``.
    """

    fill_id: str
    order_id: str
    symbol: str
    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    fee_coin: str
    timestamp_ms: int


class PionexTradeClient:
    """Signed access to the Pionex spot Trade API. This class CAN move money.

    Its read-only sibling ``PionexReadOnlyClient`` exists precisely so that
    everything which only needs to look at the account never has to hold one
    of these.
    """

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._transport = PionexTransport(http, signer)

    async def place_market_buy(
        self, *, symbol: str, client_order_id: str, quote_amount: Decimal
    ) -> PionexOrderAck:
        """Spend ``quote_amount`` of the quote currency at the market price."""
        return await self._place(
            symbol=symbol,
            client_order_id=client_order_id,
            side=BUY,
            size_field="amount",
            size=quote_amount,
        )

    async def place_market_sell(
        self, *, symbol: str, client_order_id: str, base_size: Decimal
    ) -> PionexOrderAck:
        """Sell ``base_size`` of the base currency at the market price."""
        return await self._place(
            symbol=symbol,
            client_order_id=client_order_id,
            side=SELL,
            size_field="size",
            size=base_size,
        )

    async def order_id_for(self, client_order_id: str) -> str:
        """Resolves our own id into Pionex's, hop one of two.

        Raises ``PionexOrderNotFound`` only when Pionex answered successfully
        and had nothing to report, or rejected with a listed not-found code.
        Every other failure propagates as ``PionexApiError`` so the caller
        retries rather than concluding the order was never placed.
        """
        try:
            data = await self._transport.get(
                ORDER_BY_CLIENT_ORDER_ID_PATH, {"clientOrderId": client_order_id}
            )
        except PionexApiError as exc:
            if exc.code in ORDER_NOT_FOUND_CODES:
                raise PionexOrderNotFound(
                    f"Pionex has no order under client order id {client_order_id}"
                ) from exc
            raise

        if not isinstance(data, dict) or not data:
            # A successful call that reports nothing IS the answer: Pionex
            # looked and found no such order.
            raise PionexOrderNotFound(
                f"Pionex has no order under client order id {client_order_id}"
            )

        order_id = data.get("orderId")
        if order_id is None:
            raise PionexApiError(
                f"order lookup for {client_order_id} returned an order with no orderId"
            )
        return str(order_id)

    async def fills_for_order(self, order_id: str) -> list[PionexFill]:
        """Hop two. An empty list means "accepted but nothing published yet",
        which is a legitimate transient state, not an error."""
        data = await self._transport.get(FILLS_BY_ORDER_ID_PATH, {"orderId": order_id})
        return [_parse_fill(entry) for entry in _fill_entries(data)]

    async def _place(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        size_field: str,
        size: Decimal,
    ) -> PionexOrderAck:
        _assert_valid_client_order_id(client_order_id)
        if size <= 0:
            raise PionexApiError(f"{size_field} must be positive, got {size}")

        data = await self._transport.post(
            NEW_ORDER_PATH,
            {
                "symbol": symbol,
                "side": side,
                "type": MARKET,
                "clientOrderId": client_order_id,
                size_field: _plain(size),
            },
        )

        if not isinstance(data, dict):
            raise PionexApiError("new order returned no data object")

        order_id = data.get("orderId")
        if order_id is None:
            raise PionexApiError("new order returned no orderId")

        # Pionex echoes the client order id back. If it ever echoes a
        # different one, the handle this system uses to recover the order does
        # not name the order Pionex actually created, and settlement would go
        # looking for something that is not there.
        echoed = data.get("clientOrderId")
        if echoed is not None and str(echoed) != client_order_id:
            raise PionexApiError(
                f"Pionex echoed client order id {echoed!r} for an order placed as "
                f"{client_order_id!r}; the order cannot be tracked by our own id"
            )

        return PionexOrderAck(order_id=str(order_id), client_order_id=client_order_id)


def _plain(value: Decimal) -> str:
    """Formats a ``Decimal`` without scientific notation.

    ``str(Decimal("0.00000001"))`` is fine, but ``str(Decimal("1E-8"))`` is
    ``'1E-8'`` -- and a ``Decimal`` that came out of a division very much can
    carry that exponent. Pionex expects a plain decimal string; ``1E-8`` is a
    rejected order at best.
    """
    return format(value.normalize(), "f")


def _assert_valid_client_order_id(client_order_id: str) -> None:
    if not client_order_id or len(client_order_id) > CLIENT_ORDER_ID_MAX_LENGTH:
        raise PionexApiError(
            f"clientOrderId must be 1-{CLIENT_ORDER_ID_MAX_LENGTH} characters, "
            f"got {len(client_order_id)}"
        )
    if not set(client_order_id) <= _CLIENT_ORDER_ID_ALPHABET:
        raise PionexApiError(
            "clientOrderId must contain only letters, numbers and hyphens"
        )


def _fill_entries(data: Any) -> list[Any]:
    """Accepts either shape Pionex might use.

    The balances endpoint wraps its list as ``{"balances": [...]}``, so a
    ``fills`` key is the shape to expect here -- but that has not been
    confirmed against a live fill, and a bare list is the other plausible
    reading. Accepting both is cheap; guessing wrong and raising on a real
    fill is not.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        fills = data.get("fills")
        if isinstance(fills, list):
            return fills
    raise PionexApiError("fills payload is neither a list nor an object with fills")


def _parse_fill(entry: Any) -> PionexFill:
    if not isinstance(entry, dict):
        raise PionexApiError("fill entry is not an object")

    return PionexFill(
        fill_id=_require_str(entry, "id"),
        order_id=_require_str(entry, "orderId"),
        symbol=_require_str(entry, "symbol"),
        side=_require_str(entry, "side"),
        price=_amount(entry, "price"),
        size=_amount(entry, "size"),
        fee=_amount(entry, "fee"),
        fee_coin=_require_str(entry, "feeCoin"),
        timestamp_ms=_require_int(entry, "timestamp"),
    )


def _require_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if value is None or value == "":
        raise PionexApiError(f"fill entry has no {field}")
    return str(value)


def _require_int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int):
        raise PionexApiError(
            f"fill.{field} must be an integer, got {type(value).__name__}"
        )
    return value


def _amount(entry: dict[str, Any], field: str) -> Decimal:
    """Same rule as the balance reader: a JSON number has already lost
    precision before it reaches us, so it is rejected rather than coerced.
    This is a fill price -- it lands in the append-only ledger and can never
    be corrected there.
    """
    value = entry.get(field)
    if not isinstance(value, str):
        raise PionexApiError(
            f"fill.{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"fill.{field} is not a valid decimal: {value!r}") from exc
