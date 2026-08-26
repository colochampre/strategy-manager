"""``BybitFuturesExchangeAdapter``: the live ``ExchangePort`` for USDT-M
perpetuals on Bybit.

This is the adapter that can actually run. Its Pionex twin is complete,
tested and correct, and cannot execute, because Pionex does not offer futures
order placement over its API to public users. That the two are near-identical
in shape is the argument for where the seam was cut: nothing above this layer
changed to accommodate a whole new exchange.

**What it inherits unchanged, because the reasoning is not venue-specific:**

Only failures the venue demonstrably decided become ``ExchangeError``. A
rejection carrying a business code means it saw the order and refused it, so
``PlaceOrder`` may release the reservation. A server error, a timeout, a rate
limit or a timestamp-window rejection means we do not know — and a request
that timed out may well have opened a leveraged position. Those propagate as
``BybitApiError``, the job retries, and the settle job enqueued before the
network call resolves the truth by client order id.

Sizing an opening order reads the account's leverage for the symbol, because
``AllocateCapital`` grants MARGIN out of the wallet and the position that
margin supports is ``granted * leverage / price``. The read is refused rather
than defaulted: a default would size a position at the wrong multiple of the
capital actually reserved, silently.

The size is rounded and validated at BUILD time, so the number ``PlaceOrder``
commits to its transaction is exactly the number that goes on the wire.

**What differs from Pionex, and why:**

Settlement is one hop. Bybit's execution endpoint accepts our own
``orderLinkId``, so there is no exchange-order-id resolution step to fail
between placing and settling.

"No fills" and "no order" are asked separately. An empty execution list is a
legitimate transient state, so it is not evidence the order never existed —
that question goes to the order endpoints, and only a positive "no such
order" releases capital.

``contractType`` is checked before every order. Bybit lists 40 dated futures
alongside 800 perpetuals under one ``linear`` category, and a dated contract
traded as a perpetual settles underneath the position.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
    PlacedOrder,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import (
    FuturesMarketOrder,
    close_futures_order,
    futures_position_size,
)
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.shared.domain.money import Venue
from strategy_manager.shared.infrastructure.bybit.errors import (
    BybitApiError,
    BybitOrderNotFound,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    AMBIGUOUS_CODES,
    BybitExecution,
    BybitTradeClient,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# HTTP statuses that mean the venue answered, but not with a decision about
# this order. 408 is a timeout it reported itself; 429 is throttling; 5xx is
# its own failure.
AMBIGUOUS_STATUSES = frozenset({408, 429})


class BybitFuturesExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort`` against Bybit
    USDT-M linear perpetuals."""

    is_live = True

    # USDT-M only. Bybit also settles linear perpetuals in USDC, but USDC is
    # not in the ``Currency`` enum or the ``capital_pools`` CHECK constraint,
    # so declaring it here would let a signal route to an adapter whose orders
    # no pool can fund.
    venues = frozenset({Venue.USDT_M.value})

    def __init__(self, client: BybitTradeClient) -> None:
        self._client = client

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Sizes a position from reserved margin at the account's leverage.

        Three things happen here that cannot happen anywhere else: the
        leverage is read from the venue, the size is truncated to the
        contract's step, and every limit that would get the order rejected is
        checked while the reference price is still in hand.
        """
        leverage = await self._client.leverage_for(spec.symbol)
        rules = await self._client.perp_rules(spec.symbol)

        raw = futures_position_size(
            granted=spec.granted, leverage=leverage, price=spec.price
        )
        qty = rules.round_qty(raw)
        if qty <= 0:
            raise ExchangeError(
                f"{spec.symbol} rounds a size of {raw} down to {qty} at a step of "
                f"{rules.qty_step}; the granted {spec.granted} is too small to "
                f"open a position at {leverage}x"
            )
        rules.assert_tradable(qty, spec.price)

        return FuturesMarketOrder(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            side=spec.side,
            base_size=qty,
            leverage=leverage,
            reduce_only=False,
        )

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        """Builds the reduce-only order that flattens what the ledger holds.

        Both directions are supported, which is the whole reason a futures
        venue exists here: a short is closed by buying back the same quantity,
        and spot cannot express that.

        Truncated DOWN, so a close never asks the venue to reduce more than
        the position holds.
        """
        rules = await self._client.perp_rules(spec.symbol)
        qty = rules.round_qty(spec.base_size)
        if qty <= 0:
            raise ExchangeError(
                f"{spec.symbol} rounds a held size of {spec.base_size} down to "
                f"{qty} at a step of {rules.qty_step}; the position is smaller "
                "than one tradable unit and cannot be closed by an order"
            )
        rules.assert_tradable(qty, price=None)

        return close_futures_order(
            side=spec.side,
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            base_size=qty,
        )

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        """Sends the order exactly as it was built."""
        if not isinstance(order, FuturesMarketOrder):
            # Routing should never send a spot order here: this adapter
            # declares only the usdt-m venue and the composition root maps
            # venue to adapter. Refused loudly rather than mis-sent, because
            # the failure it guards is an order sized against one wallet and
            # placed against another.
            raise ExchangeError(
                f"{type(order).__name__} is not a futures order; this adapter "
                f"trades {', '.join(sorted(self.venues))} only"
            )

        try:
            ack = await self._client.place_market_order(
                symbol=order.symbol,
                order_link_id=order.client_order_id,
                side=_bybit_side(order),
                qty=order.base_size,
                reduce_only=order.reduce_only,
            )
        except BybitApiError as exc:
            if _is_definitive_rejection(exc):
                raise ExchangeError(str(exc)) from exc
            # Ambiguous: re-raised as-is so PlaceOrder does NOT release the
            # reservation. This branch is the difference between retrying and
            # forgetting a live leveraged position.
            raise

        return PlacedOrder(
            exchange_order_id=ack.order_id, client_order_id=ack.order_link_id
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        """One hop: Bybit's execution endpoint takes our own id.

        ``symbol`` is unused because ``orderLinkId`` outranks every other
        filter. It stays in the signature because the port is written for
        exchanges generally, and some do require the market.

        An empty result is NOT read as "no such order". That question is asked
        separately, and only a venue that positively reports no such order
        produces ``OrderNotFound`` — which ``SettleExecution`` acts on by
        releasing the capital behind it.
        """
        del symbol

        executions = await self._client.fills_for(client_order_id)
        if executions:
            return [_to_domain_fill(execution) for execution in executions]

        try:
            await self._client.assert_order_placed(client_order_id)
        except BybitOrderNotFound as exc:
            raise OrderNotFound(str(exc)) from exc

        # The order exists and has published nothing yet. That is transient,
        # and the settle job retries rather than concluding anything.
        return []


def _bybit_side(order: FuturesMarketOrder) -> str:
    """Bybit spells the side ``Buy``/``Sell``; this project's domain uses
    ``BUY``/``SELL``. Translated at the boundary rather than by storing
    Bybit's spelling in the domain."""
    return order.side.value.capitalize()


def _is_definitive_rejection(error: BybitApiError) -> bool:
    """Did Bybit decide about this order, or do we simply not know?

    A business ``retCode`` means it evaluated the request and refused it. The
    listed codes are the exceptions: server errors, timeouts, rate limits and
    timestamp-window rejections leave the order's fate unknown, as does a 5xx,
    a 408, a 429 or a transport failure with no status at all.
    """
    if error.code is not None:
        return error.code not in AMBIGUOUS_CODES
    status = error.http_status
    if status is None:
        return False
    return 400 <= status < 500 and status not in AMBIGUOUS_STATUSES


def _to_domain_fill(execution: BybitExecution) -> Fill:
    """A Bybit execution reports quantity in the base coin whichever way the
    order went, so this mapping is the same for a long and a short."""
    return Fill(
        exchange_order_id=execution.order_id,
        exchange_fill_id=execution.exec_id,
        quantity=execution.qty,
        price=execution.price,
        fee=execution.fee,
        fee_currency=execution.fee_currency,
        filled_at=_from_millis(execution.exec_time_ms),
    )


def _from_millis(timestamp_ms: int) -> datetime:
    """Built by addition rather than ``fromtimestamp(ms / 1000)`` so no float
    division stands between the exchange's timestamp and a ledger row."""
    return _EPOCH + timedelta(milliseconds=timestamp_ms)
