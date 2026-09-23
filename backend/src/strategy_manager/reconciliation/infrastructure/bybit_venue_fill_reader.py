"""Implements ``VenueFillReaderPort`` over the read-only Bybit client.

The client (``BybitReadOnlyClient.fills_in_window``) owns pagination, the
``max_pages`` bound, and Bybit's own ``execType`` filtering — every decision
that needs Bybit's wire shape to make. This reader owns the two decisions
that are venue-AGNOSTIC business rules, applied identically for every venue
(design decision 9): normalising ``side`` into ``'BUY'``/``'SELL'`` and
refusing a non-positive quantity, and translating a transport failure into
the ONE exception a booking sweep is allowed to swallow per discrepancy.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.execution.domain.market_symbol import strip_contract_marker
from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenueFill,
    VenueFillReadError,
)
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import (
    BybitReadOnlyClient,
    BybitWindowExecution,
)

_EPOCH = datetime.fromtimestamp(0, UTC)

# Bybit's own spelling, normalised to this project's convention. Anything
# else is a shape this reader has never seen and must not guess at.
_SIDE_MAP = {"Buy": "BUY", "Sell": "SELL"}


class BybitVenueFillReader:
    """Implements ``VenueFillReaderPort`` for the Bybit ``usdt-m`` pool."""

    exchange = "bybit"
    venues = frozenset({"usdt-m"})

    def __init__(
        self, client: BybitReadOnlyClient, *, page_limit: int, max_pages: int
    ) -> None:
        self._client = client
        self._page_limit = page_limit
        self._max_pages = max_pages

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        # Bybit lists ``STXUSDT``, never ``STXUSDT.P`` — sending the marker
        # produces "no such symbol" for a market that plainly exists.
        venue_symbol = strip_contract_marker(symbol)
        try:
            executions = await self._client.fills_in_window(
                venue_symbol,
                start,
                end,
                page_limit=self._page_limit,
                max_pages=self._max_pages,
            )
        except BybitApiError as exc:
            raise VenueFillReadError(
                f"Bybit fill window read failed for pool {pool} symbol "
                f"{symbol}: {exc}"
            ) from exc

        return [_to_venue_fill(execution) for execution in executions]


def _to_venue_fill(execution: BybitWindowExecution) -> VenueFill:
    side = _SIDE_MAP.get(execution.side)
    if side is None:
        raise VenueFillReadError(
            f"Bybit execution {execution.exec_id} reports side "
            f"{execution.side!r}; only Buy/Sell are recognised"
        )
    if execution.qty <= 0:
        raise VenueFillReadError(
            f"Bybit execution {execution.exec_id} reports non-positive "
            f"quantity {execution.qty}"
        )
    return VenueFill(
        exchange_fill_id=execution.exec_id,
        exchange_order_id=execution.order_id,
        symbol=execution.symbol,
        side=side,
        quantity=execution.qty,
        price=execution.price,
        fee=execution.fee,
        fee_currency=execution.fee_currency,
        filled_at=_from_millis(execution.exec_time_ms),
    )


def _from_millis(timestamp_ms: int) -> datetime:
    """Built by addition rather than ``fromtimestamp(ms / 1000)`` so no
    float division stands between the exchange's timestamp and a ledger
    row (mirrors ``execution.infrastructure.bybit_futures_exchange``)."""
    return _EPOCH + timedelta(milliseconds=timestamp_ms)
