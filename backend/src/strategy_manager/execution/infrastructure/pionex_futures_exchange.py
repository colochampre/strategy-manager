"""``PionexFuturesExchangeAdapter``: the live ``ExchangePort`` for USDT-M
perpetuals.

The sibling of ``pionex_exchange.py``, and it inherits that module's central
rule verbatim, because getting it wrong costs the same money:

**Only failures Pionex demonstrably decided become ``ExchangeError``.** A
rejection envelope or a 4xx means it answered and said no, so ``PlaceOrder``
may release the reservation. A timeout, a 5xx, a 408 or 429, or a transport
failure means we do not know -- and a request that timed out may well have
opened a leveraged position. Those propagate as ``PionexApiError``, the job
retries, and the settle job enqueued before the network call resolves the
truth by client order id.

**What differs from spot, and why the difference is load-bearing.**

Sizing an opening order needs a number that is not in the reservation: the
account's leverage for that symbol. ``AllocateCapital`` grants MARGIN out of
the futures wallet, and the position that margin supports is
``granted * leverage / price``. So ``build_open_order`` reaches the network,
and it refuses rather than guessing if that read fails -- a default here would
size a position at the wrong multiple of the capital that was actually
reserved, silently, and the error would only be visible as an inexplicable
account balance.

The size is rounded and validated at BUILD time rather than at place time, so
the number ``PlaceOrder`` commits to its transaction is exactly the number
that goes on the wire. Spot rounds inside ``place`` and records the unrounded
size; that is a smaller discrepancy there because a spot buy carries the
granted amount untouched, but there is no reason to repeat it here.

Closing needs no leverage at all: the size comes from the ledger. So a close
touches no account setting and cannot fail because one could not be read.

**Venue scope.** ``usdt-m`` only. Coin-margined perpetuals reach the same API
and the same 43 contracts are listed, but they settle in currencies the
``Currency`` enum and the ``capital_pools`` CHECK constraint do not yet carry.
Declaring ``coin-m`` here would let a signal route to an adapter whose orders
no pool can fund.
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
from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.fills import PionexFill
from strategy_manager.shared.infrastructure.pionex.futures_trade_client import (
    PionexFuturesTradeClient,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# Statuses meaning "Pionex answered, but not with a decision about this
# order". 408 is a timeout it reported itself; 429 is throttling; 5xx is its
# own failure. None of them says whether the order was accepted.
AMBIGUOUS_STATUSES = frozenset({408, 429})


class PionexFuturesExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort`` against Pionex
    USDT-M futures."""

    is_live = True

    venues = frozenset({Venue.USDT_M.value})

    def __init__(self, client: PionexFuturesTradeClient) -> None:
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
        size = rules.round_base_size(raw)
        if size <= 0:
            raise ExchangeError(
                f"{spec.symbol} rounds a size of {raw} down to {size} at a step "
                f"of {rules.base_step}; the granted {spec.granted} is too small "
                f"to open a position at {leverage}x"
            )
        rules.assert_tradable(size, spec.price)

        return FuturesMarketOrder(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            side=spec.side,
            base_size=size,
            leverage=leverage,
            reduce_only=False,
        )

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        """Builds the reduce-only order that flattens what the ledger holds.

        Both directions are supported, which is the whole reason a futures
        venue exists here: a short is closed by buying back the same base
        quantity, and ``MARKET_QTY`` can express that. Spot cannot.

        The size is truncated DOWN, so a close never asks the venue to reduce
        more than the position holds.
        """
        rules = await self._client.perp_rules(spec.symbol)
        size = rules.round_base_size(spec.base_size)
        if size <= 0:
            raise ExchangeError(
                f"{spec.symbol} rounds a held size of {spec.base_size} down to "
                f"{size} at a step of {rules.base_step}; the position is smaller "
                "than one tradable unit and cannot be closed by an order"
            )

        return close_futures_order(
            side=spec.side,
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            base_size=size,
        )

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        """Sends the order exactly as it was built.

        ``reference_price`` is not passed: the minimum-notional fail-safe
        already ran at build time, against the price that sized the order. A
        close has no price at all, so there is nothing to check it with.
        """
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
                client_order_id=order.client_order_id,
                side=order.side.value,
                base_size=order.base_size,
                reduce_only=order.reduce_only,
                reference_price=None,
            )
        except PionexApiError as exc:
            if _is_definitive_rejection(exc):
                raise ExchangeError(str(exc)) from exc
            # Ambiguous: re-raised as-is so PlaceOrder does NOT release the
            # reservation. This branch is the difference between retrying and
            # forgetting a live leveraged position.
            raise

        return PlacedOrder(
            exchange_order_id=ack.order_id, client_order_id=ack.client_order_id
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        """Two hops, hidden behind one intent (see ``futures_trade_client``).

        ``symbol`` is unused: Pionex keys both hops by id alone. It stays in
        the signature because the port is written for exchanges generally.

        Only ``PionexOrderNotFound`` becomes ``OrderNotFound``. Every other
        failure propagates, because ``SettleExecution`` reads ``OrderNotFound``
        as "the order never existed, release the capital" and a failed lookup
        is not evidence of that.
        """
        del symbol

        try:
            order_id = await self._client.order_id_for(client_order_id)
        except PionexOrderNotFound as exc:
            raise OrderNotFound(str(exc)) from exc

        fills = await self._client.fills_for_order(order_id)
        return [_to_domain_fill(fill) for fill in fills]


def _is_definitive_rejection(error: PionexApiError) -> bool:
    """Did Pionex decide about this order, or do we simply not know?

    A rejection envelope carries a code: Pionex parsed the request and refused
    it. A 4xx says the same at the HTTP layer. Everything else -- no status at
    all (a transport failure), a 5xx, or the two 4xx statuses meaning "try
    again" -- leaves the order's fate unknown.
    """
    if error.code is not None:
        return True
    status = error.http_status
    if status is None:
        return False
    return 400 <= status < 500 and status not in AMBIGUOUS_STATUSES


def _to_domain_fill(fill: PionexFill) -> Fill:
    """A futures fill reports the same fields a spot one does, so this mapping
    is identical -- and identical for a long and a short, because
    ``MARKET_QTY`` is base-denominated both ways."""
    return Fill(
        exchange_order_id=fill.order_id,
        exchange_fill_id=fill.fill_id,
        quantity=fill.size,
        price=fill.price,
        fee=fill.fee,
        fee_currency=fill.fee_coin,
        filled_at=_from_millis(fill.timestamp_ms),
    )


def _from_millis(timestamp_ms: int) -> datetime:
    """Built by addition rather than ``fromtimestamp(ms / 1000)`` so no float
    division stands between the exchange's timestamp and a ledger row."""
    return _EPOCH + timedelta(milliseconds=timestamp_ms)
