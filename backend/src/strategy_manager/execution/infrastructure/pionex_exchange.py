"""``PionexExchangeAdapter``: the live ``ExchangePort`` (CLAUDE.md rule 1 --
this is the adapter whose existence lets ``DRY_RUN=false`` start at all).

Its whole job is translation between two vocabularies, and one translation in
it is far more dangerous than the rest.

**Definitive rejection vs. "we do not know".**

``PlaceOrder`` treats ``ExchangeError`` as final: it releases the reservation
and marks the attempt FAILED, and because the attempt is then terminal, the
already-scheduled settlement job returns ALREADY_SETTLED without ever asking
the exchange anything. That is exactly right for a rejection -- Pionex saw the
order and refused it, so there is nothing to reconcile.

It is exactly wrong for a timeout. A request that timed out may well have
reached Pionex and opened a position. Reporting that as ``ExchangeError``
would release the capital backing a live trade and close the only door left
open to discovering it. The money would be in the market and this system would
have no record that it ever tried.

So the rule here is: **only failures Pionex demonstrably decided become
``ExchangeError``.** Everything ambiguous propagates as ``PionexApiError``,
which ``PlaceOrder`` does not catch -- the job fails, the worker retries it,
and the settle job enqueued before the network call resolves the truth by
client order id either way. The retry cannot double-order: the UNIQUE
constraint on ``execution_attempts.reservation_id`` refuses a second attempt
for the same reservation.

Deciding which is which comes down to whether Pionex answered:

- a rejection envelope (``result: false`` with a code) -- it answered, and
  said no
- HTTP 4xx other than 408/429 -- it answered, and rejected the request
- a transport failure, a timeout, HTTP 5xx, 408 or 429 -- it did not answer,
  or answered "not now". We do not know what happened to the order.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.execution.application.ports import (
    ExchangeError,
    OrderNotFound,
    PlacedOrder,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import MarketBuy, MarketSell, OrderRequest
from strategy_manager.shared.domain.money import Venue
from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.fills import PionexFill
from strategy_manager.shared.infrastructure.pionex.trade_client import (
    PionexTradeClient,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# HTTP statuses that mean "Pionex answered, but not with a decision about this
# order". 408 is a timeout it reported itself; 429 is throttling; 5xx is its
# own failure. None of them says whether the order was accepted.
AMBIGUOUS_STATUSES = frozenset({408, 429})


class PionexExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort`` against Pionex
    spot.

    ``is_live = True`` is the whole point: this is the only registered adapter
    for which the startup invariant permits ``DRY_RUN=false``.
    """

    is_live = True

    # Spot only. ``PionexTradeClient`` speaks ``/api/v1/``, and Pionex's
    # futures API is a different base path with different semantics, so a
    # futures pool needs a different adapter rather than this one pointed
    # somewhere else.
    venues = frozenset({Venue.SPOT.value})

    def __init__(self, client: PionexTradeClient) -> None:
        self._client = client

    async def place(self, order: OrderRequest) -> PlacedOrder:
        """Sends the order in whichever denomination its variant carries.

        There is no side flag to get wrong here — a ``MarketBuy`` can only
        reach ``place_market_buy``, which can only send ``amount``.
        """
        try:
            match order:
                case MarketBuy():
                    ack = await self._client.place_market_buy(
                        symbol=order.symbol,
                        client_order_id=order.client_order_id,
                        quote_amount=order.quote_amount,
                    )
                case MarketSell():
                    ack = await self._client.place_market_sell(
                        symbol=order.symbol,
                        client_order_id=order.client_order_id,
                        base_size=order.base_size,
                    )
        except PionexApiError as exc:
            if _is_definitive_rejection(exc):
                raise ExchangeError(str(exc)) from exc
            # Ambiguous: re-raised as-is so PlaceOrder does NOT release the
            # reservation. See this module's docstring — this branch is the
            # difference between retrying and forgetting a live position.
            raise

        return PlacedOrder(
            exchange_order_id=ack.order_id, client_order_id=ack.client_order_id
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        """Two hops, hidden behind one intent (see ``trade_client``).

        ``symbol`` is unused: Pionex keys both hops by id alone. It stays in
        the signature because the port is written for exchanges generally, and
        some do require the market to look an order up.

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

        return [_to_domain_fill(fill) for fill in await self._client.fills_for_order(order_id)]


def _is_definitive_rejection(error: PionexApiError) -> bool:
    """Did Pionex decide about this order, or do we simply not know?

    A rejection envelope carries a code: Pionex parsed the request and
    refused it. A 4xx says the same thing at the HTTP layer. Everything else —
    no status at all (a transport failure), a 5xx, or the two 4xx statuses
    that mean "try again" — leaves the order's fate unknown.
    """
    if error.code is not None:
        return True
    status = error.http_status
    if status is None:
        return False
    return 400 <= status < 500 and status not in AMBIGUOUS_STATUSES


def _to_domain_fill(fill: PionexFill) -> Fill:
    """Pionex reports a fill in base ``size`` whichever way the order was
    denominated, so this mapping is the same for a buy and a sell."""
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
