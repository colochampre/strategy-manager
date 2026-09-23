"""Implements ``VenueFillReaderPort`` over the read-only Binance client.

The client (``BinanceReadOnlyClient.fills_in_window``) owns pagination and
the ``max_pages``/zero-new-ids bounds — every decision that needs Binance's
wire shape and its own pagination trap to make. This reader owns the two
decisions that are venue-AGNOSTIC business rules, applied identically for
every venue (design decision 9): normalising ``side`` into
``'BUY'``/``'SELL'`` and refusing a non-positive quantity, and translating a
transport failure into the ONE exception a booking sweep is allowed to
swallow per discrepancy.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.execution.domain.market_symbol import strip_contract_marker
from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenueFill,
    VenueFillReadError,
)
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
    BinanceWindowTrade,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# Binance's own spelling, normalised to this project's convention. Anything
# else is a shape this reader has never seen and must not guess at.
_SIDE_MAP = {"BUY": "BUY", "SELL": "SELL"}


class BinanceVenueFillReader:
    """Implements ``VenueFillReaderPort`` for the Binance ``usdt-m`` pool."""

    exchange = "binance"
    venues = frozenset({"usdt-m"})

    def __init__(
        self, client: BinanceReadOnlyClient, *, page_limit: int, max_pages: int
    ) -> None:
        self._client = client
        self._page_limit = page_limit
        self._max_pages = max_pages

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        # Binance lists ``STXUSDT``, never ``STXUSDT.P`` -- sending the
        # marker produces "no such symbol" for a market that plainly exists.
        venue_symbol = strip_contract_marker(symbol)
        try:
            trades = await self._client.fills_in_window(
                venue_symbol,
                start,
                end,
                page_limit=self._page_limit,
                max_pages=self._max_pages,
            )
        except BinanceApiError as exc:
            raise VenueFillReadError(
                f"Binance fill window read failed for pool {pool} symbol "
                f"{symbol}: {exc}"
            ) from exc

        return [_to_venue_fill(trade) for trade in trades]


def _to_venue_fill(trade: BinanceWindowTrade) -> VenueFill:
    side = _SIDE_MAP.get(trade.side)
    if side is None:
        raise VenueFillReadError(
            f"Binance trade {trade.trade_id} reports side {trade.side!r}; "
            "only BUY/SELL are recognised"
        )
    if trade.qty <= 0:
        raise VenueFillReadError(
            f"Binance trade {trade.trade_id} reports non-positive quantity "
            f"{trade.qty}"
        )
    return VenueFill(
        exchange_fill_id=str(trade.trade_id),
        exchange_order_id=str(trade.order_id) if trade.order_id is not None else None,
        symbol=trade.symbol,
        side=side,
        quantity=trade.qty,
        price=trade.price,
        fee=trade.commission,
        fee_currency=trade.commission_asset,
        filled_at=_from_millis(trade.trade_time_ms),
    )


def _from_millis(timestamp_ms: int) -> datetime:
    """Built by addition rather than ``fromtimestamp(ms / 1000)`` so no
    float division stands between the exchange's timestamp and a ledger
    row (mirrors ``execution.infrastructure.binance_futures_exchange``)."""
    return _EPOCH + timedelta(milliseconds=timestamp_ms)
