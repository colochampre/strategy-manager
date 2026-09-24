"""``BinanceFuturesExchangeAdapter``: the live ``ExchangePort`` for USDⓈ-M
perpetuals on Binance.

The second adapter that can actually run, and the one that proves the seam
held: nothing above this layer changed to admit a whole second exchange. Its
Bybit twin is the reference, and everything below is either inherited from it
unchanged or a place where Binance genuinely differs.

**What it inherits unchanged, because the reasoning is not venue-specific:**

Only failures the venue demonstrably decided become ``ExchangeError``. A
rejection carrying a business code means it saw the order and refused it, so
``PlaceOrder`` may release the reservation. A server error, a timeout or a rate
limit means we do not know — and a request that timed out may well have opened
a leveraged position. Those propagate as ``BinanceApiError``, the job retries,
and the settle job enqueued before the network call resolves the truth by
client order id.

Sizing an opening order reads the account's leverage for the symbol, because
``AllocateCapital`` grants MARGIN out of the wallet and the position that
margin supports is ``granted * leverage / price``. The read is refused rather
than defaulted: a default would size a position at the wrong multiple of the
capital actually reserved, silently.

The size is rounded and validated at BUILD time, so the number ``PlaceOrder``
commits to its transaction is exactly the number that goes on the wire.

``contractType`` is checked before every order. Binance's catalogue mixes 897
contracts of three products — perpetuals, dated quarterlies and 191
``TRADIFI_PERPETUAL`` entries — and both of the others settle or expire
underneath a position held in them.

**What differs from Bybit, and why:**

Settlement takes two hops. Bybit's execution endpoint accepts our own
``orderLinkId``; Binance's ``/fapi/v1/userTrades`` accepts ``symbol`` and a
numeric ``orderId`` only, so the client order id has to be resolved into
Binance's id first. That lookup is also what answers "does this order exist at
all", which on Bybit is a separate call.

The side needs no translation. Binance spells it ``BUY``/``SELL``, which is
already ``OrderSide.value``, where Bybit says ``Buy``/``Sell``.

The ids arrive as JSON integers rather than strings, so they are converted
explicitly on the way into the domain.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
    OrderNotPlaceable,
    PlacedOrder,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import (
    FuturesMarketOrder,
    close_futures_order,
    futures_position_size,
)
from strategy_manager.execution.domain.market_symbol import strip_contract_marker
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.shared.domain.money import Exchange, Venue
from strategy_manager.shared.infrastructure.binance.errors import (
    BinanceApiError,
    BinanceOrderNotFound,
    BinanceRuleRefusal,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    AMBIGUOUS_CODES,
    BinanceExecution,
    BinanceTradeClient,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# HTTP statuses that mean the venue answered, but not with a decision about
# this order. 408 is a timeout it reported itself and 429 is throttling; every
# 5xx is its own failure and is already excluded by the 4xx range below.
AMBIGUOUS_STATUSES = frozenset({408, 429})


class BinanceFuturesExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort`` against Binance
    USDⓈ-M perpetuals."""

    is_live = True

    exchange = Exchange.BINANCE.value

    # USDⓈ-M only. Binance also settles perpetuals in USDC under this same API,
    # but USDC is not in the ``Currency`` enum or the ``capital_pools`` CHECK
    # constraint, so declaring it here would let a signal route to an adapter
    # whose orders no pool can fund.
    venues = frozenset({Venue.USDT_M.value})

    def __init__(self, client: BinanceTradeClient) -> None:
        self._client = client

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Sizes a position from reserved margin at the account's leverage.

        Three things happen here that cannot happen anywhere else: the
        leverage is read from the venue, the size is truncated to the
        contract's step, and every limit that would get the order rejected is
        checked while the reference price is still in hand.
        """
        symbol = _venue_symbol(spec.symbol)
        leverage = await self._client.leverage_for(symbol)
        rules = await self._client.perp_rules(symbol)

        raw = futures_position_size(
            granted=spec.granted, leverage=leverage, price=spec.price
        )
        qty = rules.round_qty(raw)
        if qty <= 0:
            raise OrderNotPlaceable(
                f"{symbol} rounds a size of {raw} down to {qty} at a step of "
                f"{rules.qty_step}; the granted {spec.granted} is too small to "
                f"open a position at {leverage}x",
                symbol=symbol,
                size=qty,
                minimum=rules.min_qty,
                step=rules.qty_step,
            )
        try:
            rules.assert_tradable(qty, spec.price)
        except BinanceRuleRefusal as exc:
            # The venue's own catalogue already decided -- definitively,
            # unlike a leverage or instrument read that merely failed above.
            # Retrying re-asks a question the venue has already answered.
            raise OrderNotPlaceable(
                str(exc),
                symbol=symbol,
                size=qty,
                minimum=rules.min_qty,
                step=rules.qty_step,
            ) from exc

        return FuturesMarketOrder(
            client_order_id=spec.client_order_id,
            symbol=symbol,
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

        No account setting is read. A close that fails because a descriptive
        field could not be fetched leaves a real position open at the venue.
        """
        symbol = _venue_symbol(spec.symbol)
        rules = await self._client.perp_rules(symbol)
        qty = rules.round_qty(spec.base_size)
        if qty <= 0:
            raise OrderNotPlaceable(
                f"{symbol} rounds a held size of {spec.base_size} down to "
                f"{qty} at a step of {rules.qty_step}; the position is smaller "
                "than one tradable unit and cannot be closed by an order",
                symbol=symbol,
                size=qty,
                minimum=rules.min_qty,
                step=rules.qty_step,
            )
        try:
            rules.assert_tradable(qty, price=None)
        except BinanceRuleRefusal as exc:
            raise OrderNotPlaceable(
                str(exc),
                symbol=symbol,
                size=qty,
                minimum=rules.min_qty,
                step=rules.qty_step,
            ) from exc

        return close_futures_order(
            side=spec.side,
            client_order_id=spec.client_order_id,
            symbol=symbol,
            base_size=qty,
        )

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        """Sends the order exactly as it was built."""
        if not isinstance(order, FuturesMarketOrder):
            # Routing should never send a spot order here: this adapter
            # declares only the usdt-m venue and the composition root maps
            # exchange and venue to adapter. Refused loudly rather than
            # mis-sent, because the failure it guards is an order sized against
            # one wallet and placed against another.
            raise ExchangeError(
                f"{type(order).__name__} is not a futures order; this adapter "
                f"trades {', '.join(sorted(self.venues))} only"
            )

        try:
            ack = await self._client.place_market_order(
                symbol=order.symbol,
                client_order_id=order.client_order_id,
                # Binance spells the side BUY/SELL, which is exactly what
                # ``OrderSide.value`` already is. Passed through deliberately:
                # its Bybit twin capitalises here, and "fixing" this one to
                # match would send a side Binance does not accept.
                side=order.side.value,
                qty=order.base_size,
                reduce_only=order.reduce_only,
            )
        except BinanceApiError as exc:
            if _is_definitive_rejection(exc):
                raise ExchangeError(str(exc)) from exc
            # Ambiguous: re-raised as-is so PlaceOrder does NOT release the
            # reservation. This branch is the difference between retrying and
            # forgetting a live leveraged position.
            raise

        # ``orderId`` is a JSON integer on this venue where Bybit sends a
        # string, and the domain's handle is a string. Converted here rather
        # than left to whatever stringifies it downstream.
        return PlacedOrder(
            exchange_order_id=str(ack.order_id), client_order_id=ack.client_order_id
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        """Two hops: our own id, then Binance's, then the fills.

        ``symbol`` is load-bearing here, which is why the port carries it at
        all. Bybit settles from ``orderLinkId`` alone; both Binance endpoints
        scope a lookup to one market, so the id by itself finds nothing. It is
        stripped exactly as the order path strips it — an order that reached
        the venue as ``AAVEUSDT`` cannot be looked up as ``AAVEUSDT.P``.

        The lookup hop doubles as the existence question. Only a venue that
        positively reports no such order produces ``OrderNotFound`` — which
        ``SettleExecution`` acts on by releasing the capital behind it.

        An empty fill list is therefore NOT read as "no such order": existence
        was already established one call earlier, so empty means accepted and
        not yet published, and the settle job retries.
        """
        market = _venue_symbol(symbol)

        try:
            order_id = await self._client.order_id_for(client_order_id, market)
        except BinanceOrderNotFound as exc:
            raise OrderNotFound(str(exc)) from exc

        executions = await self._client.fills_for(symbol=market, order_id=order_id)
        return [_to_domain_fill(execution) for execution in executions]


def _venue_symbol(symbol: str) -> str:
    """What Binance calls this market.

    A TradingView alert charted on a perpetual sends ``AAVEUSDT.P`` — the
    ``.P`` is TradingView's perpetual suffix, not part of the symbol. Binance
    lists it as ``AAVEUSDT``, and sending the suffix produces "no such symbol"
    for a market that plainly exists.

    Normalised at the boundary rather than at ingress on purpose: the signal
    record keeps what the alert actually said, which is what makes a
    disagreement between the two diagnosable later.
    """
    return strip_contract_marker(symbol).upper()


def _is_definitive_rejection(error: BinanceApiError) -> bool:
    """Did Binance decide about this order, or do we simply not know?

    A business code means it evaluated the request and refused it. Only
    ``-1001`` and ``-1007`` are exempt, and both are verbatim admissions that
    the outcome is unknown.

    With no code at all the answer comes from the status line: a 4xx is a
    refusal Binance issued before the order existed, while a 5xx, a 408, a 429
    or a transport failure with no status leave its fate unknown. That makes
    HTTP 451 definitive — a geo refusal is a decision, and retrying it changes
    nothing — and every 5xx ambiguous.
    """
    if error.code is not None:
        return error.code not in AMBIGUOUS_CODES
    status = error.http_status
    if status is None:
        return False
    return 400 <= status < 500 and status not in AMBIGUOUS_STATUSES


def _to_domain_fill(execution: BinanceExecution) -> Fill:
    """A USDⓈ-M execution reports quantity in the base asset whichever way the
    order went, so this mapping is the same for a long and a short.

    The ids are integers on the wire and strings in the domain. The conversion
    is not cosmetic: the ledger's UNIQUE index is
    ``(exchange, venue, exchange_fill_id)``, so ``str(trade_id)`` is what keeps
    a fill unique.
    """
    return Fill(
        exchange_order_id=str(execution.order_id),
        exchange_fill_id=str(execution.trade_id),
        quantity=execution.qty,
        price=execution.price,
        fee=execution.commission,
        fee_currency=execution.commission_asset,
        filled_at=_from_millis(execution.trade_time_ms),
    )


def _from_millis(timestamp_ms: int) -> datetime:
    """Built by addition rather than ``fromtimestamp(ms / 1000)`` so no float
    division stands between the exchange's timestamp and a ledger row."""
    return _EPOCH + timedelta(milliseconds=timestamp_ms)
