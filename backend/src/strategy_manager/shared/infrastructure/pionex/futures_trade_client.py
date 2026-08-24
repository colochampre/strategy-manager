"""Order submission and fill lookup against the Pionex futures Trade API.

The sibling of ``trade_client.py``, and a separate class rather than a flag on
it: futures orders live under ``/uapi/v1/``, carry a different order type, and
answer to constraints spot does not have.

**One order shape, both directions.** Spot needs two methods because a market
buy sends ``amount`` and a market sell sends ``size``. ``MARKET_QTY`` sends
``size`` whichever way it goes, so there is one method here and the side is a
parameter. That is not a shortcut -- it is the same principle as spot's split,
applied to a venue where the denomination genuinely does not branch.

**The account must be in one-way mode.** ``positionMode`` is ``BUYSELL``
(one-way) or ``OPENCLOSE`` (hedged), and this client is written for the first.
In hedged mode a symbol holds a long AND a short at once, ``positionSide``
becomes required on every order, and ``reduceOnly`` -- which the reference
documents as applying only in one-way mode -- stops protecting a close. Every
close would then be able to open a fresh position on the other side.

So the mode is read once and asserted before the first order. Refusing is the
only safe answer: silently placing one-way orders against a hedged account
would work often enough to look fine and fail exactly when a position is open.
``positionSide`` is deliberately omitted for the same reason it is safe to
omit -- the reference requires it only for hedge mode, and hedge mode is
refused.

**Fills need two hops**, exactly as on spot: Pionex answers a new order with
an id and nothing else, and the fills endpoint is keyed by the EXCHANGE order
id. ``clientOrderId -> order (yields orderId) -> fills``.
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
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    PionexFuturesReadClient,
)
from strategy_manager.shared.infrastructure.pionex.perp_symbols import (
    PerpRules,
    PionexPerpCatalog,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport
from strategy_manager.shared.infrastructure.pionex.wire import (
    assert_valid_client_order_id,
    plain_decimal,
)

NEW_ORDER_PATH = "/uapi/v1/trade/order"
ORDER_BY_CLIENT_ORDER_ID_PATH = "/uapi/v1/trade/orderByClientOrderId"
FILLS_BY_ORDER_ID_PATH = "/uapi/v1/trade/fillsByOrderId"

MARKET_QTY = "MARKET_QTY"
ONE_WAY_MODE: Final = "BUYSELL"

# Rejection codes meaning "this order does not exist", as opposed to "the call
# failed". VERIFIED 2026-08-24 against the owner's live futures account via
# ``backend/scripts/check_pionex_futures_lookup.py``, a read-only probe that
# looks up a random UUID and places nothing.
#
# Kept to exactly what Pionex has been observed to send, for the reason the
# spot list records at length: three plausible-sounding names were guessed for
# spot before its probe ran and every one was wrong. A guessed code that is
# wrong makes this system release the capital behind a live position.
ORDER_NOT_FOUND_CODES: Final = frozenset({"TRADE_ORDER_NOT_EXIST"})


@dataclass(frozen=True, slots=True)
class PionexOrderAck:
    """What Pionex returns when it accepts a new futures order: an id, and
    nothing about what it filled at."""

    order_id: str
    client_order_id: str


class PionexFuturesTradeClient:
    """Signed access to the Pionex futures Trade API. This class CAN move
    money.

    Its read-only sibling ``PionexFuturesReadClient`` exists so that
    everything which only needs to look at the account never holds one of
    these -- and this class composes that one rather than duplicating its
    parsing, because reading is a strict subset of what it needs to do.
    """

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._transport = PionexTransport(http, signer)
        self._symbols = PionexPerpCatalog(self._transport)
        self._read = PionexFuturesReadClient(http, signer)
        self._position_mode: str | None = None

    async def perp_rules(self, symbol: str) -> PerpRules:
        """The precision, step and size limits this market imposes.

        Public because those constraints decide whether an order is placeable
        at all, so a caller may reasonably want to see them first.
        """
        return await self._symbols.rules_for(symbol)

    async def leverage_for(self, symbol: str) -> Decimal:
        """The leverage this symbol is configured at, which is what sizes an
        opening order (``granted * leverage / price``).

        Read rather than assumed, and never defaulted. A default here would
        silently size a position at the wrong multiple of the capital the
        allocation engine granted.
        """
        return await self._read.leverage_for(symbol)

    async def assert_one_way(self) -> None:
        """Refuses a hedged account before any order is sent.

        Cached after the first read: the mode is an account setting, the
        client is built per job, and re-reading it on every order would add a
        round trip to the hot path for a number that cannot change inside one
        job.
        """
        if self._position_mode is None:
            self._position_mode = await self._read.position_mode()

        if self._position_mode.upper() != ONE_WAY_MODE:
            raise PionexApiError(
                f"the futures account is in {self._position_mode} mode; this "
                f"adapter is written for {ONE_WAY_MODE} (one-way) only. In "
                "hedge mode a symbol holds a long and a short at once, "
                "positionSide becomes required, and reduceOnly stops "
                "protecting a close"
            )

    async def place_market_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        base_size: Decimal,
        reduce_only: bool,
        reference_price: Decimal | None,
    ) -> PionexOrderAck:
        """Places a ``MARKET_QTY`` order for ``base_size`` of the base
        currency.

        ``reference_price`` never goes on the wire. It is the alert's
        bar-close price, used only for the local minimum-notional check, so a
        size the venue would refuse is refused here with the actual numbers
        in the message instead of arriving as an opaque code. The venue
        remains the authority: this is a fail-safe made against a price that
        is by definition slightly stale.

        It is ``None`` for a close, which is sized from the ledger and has no
        price of its own. Inventing one to satisfy a fail-safe would be worse
        than skipping it: a close that this system refuses locally leaves a
        real position open.

        The size is truncated DOWN to the symbol's step first. A futures size
        is always a quotient, so it essentially never lands on a step boundary
        by itself.
        """
        await self.assert_one_way()
        assert_valid_client_order_id(client_order_id)

        rules = await self._symbols.rules_for(symbol)
        size = rules.round_base_size(base_size)
        if size <= 0:
            raise PionexApiError(
                f"{symbol} rounds an order of {base_size} down to {size} at a "
                f"step of {rules.base_step}; there is nothing left to send"
            )
        rules.assert_tradable(size, reference_price)

        payload = {
            "symbol": symbol,
            "side": side,
            "type": MARKET_QTY,
            "size": plain_decimal(size),
            "clientOrderId": client_order_id,
            "reduceOnly": reduce_only,
        }
        data = await self._transport.post(NEW_ORDER_PATH, payload)

        if not isinstance(data, dict):
            raise PionexApiError("new futures order returned no data object")

        order_id = data.get("orderId")
        if order_id is None:
            raise PionexApiError("new futures order returned no orderId")

        # If Pionex ever echoes a different client order id, the handle this
        # system uses to recover the order does not name the order Pionex
        # actually created, and settlement would go looking for something that
        # is not there.
        echoed = data.get("clientOrderId")
        if echoed is not None and str(echoed) != client_order_id:
            raise PionexApiError(
                f"Pionex echoed client order id {echoed!r} for an order placed "
                f"as {client_order_id!r}; the order cannot be tracked by our own id"
            )

        return PionexOrderAck(order_id=str(order_id), client_order_id=client_order_id)

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
                    f"Pionex has no futures order under client order id "
                    f"{client_order_id}"
                ) from exc
            raise

        if not isinstance(data, dict) or not data:
            # A successful call reporting nothing IS the answer: Pionex looked
            # and found no such order.
            raise PionexOrderNotFound(
                f"Pionex has no futures order under client order id {client_order_id}"
            )

        order_id = data.get("orderId")
        if order_id is None:
            raise PionexApiError(
                f"futures order lookup for {client_order_id} returned an order "
                "with no orderId"
            )
        return str(order_id)

    async def fills_for_order(self, order_id: str) -> list[PionexFill]:
        """Hop two. An empty list means "accepted but nothing published yet",
        which is a legitimate transient state, not an error."""
        data = await self._transport.get(FILLS_BY_ORDER_ID_PATH, {"orderId": order_id})
        return parse_fills(data)
