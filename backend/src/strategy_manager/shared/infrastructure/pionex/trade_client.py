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

**Every order is rounded to the symbol's precision before it is sent.**
Pionex reports balances with far more precision than it accepts on an order,
and the ledger records fills with whatever precision they had, so both an
untouched buy amount and an untouched sell size are rejected. Rounding is
always DOWN — see ``symbols.py`` for why up is never safe.

**Fills need two hops.** Pionex answers a new order with an id and nothing
else, and its fill endpoint is keyed by the EXCHANGE order id, not the client
one. So: ``clientOrderId -> order (yields orderId) -> fills``. Both hops live
here; ``execution``'s ``fetch_fills(client_order_id, symbol)`` expresses the
intent, and this is where the mechanics stay.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import httpx

from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.fills import (
    PionexFill,
    parse_fills,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.symbols import (
    PionexSymbolCatalog,
    SymbolRules,
)
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport
from strategy_manager.shared.infrastructure.pionex.wire import (
    assert_valid_client_order_id,
    plain_decimal,
)

NEW_ORDER_PATH = "/api/v1/trade/order"
ORDER_BY_CLIENT_ORDER_ID_PATH = "/api/v1/trade/orderByClientOrderId"
FILLS_BY_ORDER_ID_PATH = "/api/v1/trade/fillsByOrderId"

MARKET = "MARKET"
BUY = "BUY"
SELL = "SELL"

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


class PionexTradeClient:
    """Signed access to the Pionex spot Trade API. This class CAN move money.

    Its read-only sibling ``PionexReadOnlyClient`` exists precisely so that
    everything which only needs to look at the account never has to hold one
    of these.
    """

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._transport = PionexTransport(http, signer)
        self._symbols = PionexSymbolCatalog(self._transport)

    async def symbol_rules(self, symbol: str) -> SymbolRules:
        """The precision and minimum constraints this market imposes.

        Public because the constraints decide whether an order is placeable at
        all, so a caller may reasonably want to see them before committing to
        one -- the live trade probe prints them.
        """
        return await self._symbols.rules_for(symbol)

    async def place_market_buy(
        self, *, symbol: str, client_order_id: str, quote_amount: Decimal
    ) -> PionexOrderAck:
        """Spend ``quote_amount`` of the quote currency at the market price.

        The amount is truncated to the symbol's ``amountPrecision`` first. A
        granted amount is a percentage of an exchange balance, and Pionex
        reports balances with far more precision than it accepts on an order.
        """
        rules = await self._symbols.rules_for(symbol)
        amount = rules.round_amount(quote_amount)
        rules.assert_amount_tradable(amount)

        return await self._place(
            symbol=symbol,
            client_order_id=client_order_id,
            side=BUY,
            size_field="amount",
            size=amount,
        )

    async def place_market_sell(
        self, *, symbol: str, client_order_id: str, base_size: Decimal
    ) -> PionexOrderAck:
        """Sell ``base_size`` of the base currency at the market price.

        Truncated to the symbol's ``basePrecision``, and DOWN: rounding a sell
        up asks the exchange for more of the base currency than the account
        holds, which is refused for insufficient balance and leaves a position
        open while this system believes it closed.
        """
        rules = await self._symbols.rules_for(symbol)
        size = rules.round_base_size(base_size)
        rules.assert_size_tradable(size)

        return await self._place(
            symbol=symbol,
            client_order_id=client_order_id,
            side=SELL,
            size_field="size",
            size=size,
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
        return parse_fills(data)

    async def _place(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        size_field: str,
        size: Decimal,
    ) -> PionexOrderAck:
        assert_valid_client_order_id(client_order_id)
        if size <= 0:
            raise PionexApiError(f"{size_field} must be positive, got {size}")

        data = await self._transport.post(
            NEW_ORDER_PATH,
            {
                "symbol": symbol,
                "side": side,
                "type": MARKET,
                "clientOrderId": client_order_id,
                size_field: plain_decimal(size),
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
