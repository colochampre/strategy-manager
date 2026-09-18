"""Implements ``VenuePositionReaderPort`` over the read-only Binance client.

``BinanceReadOnlyClient.open_positions`` already answers the WHOLE USDⓈ-M
account in one ``/fapi/v3/positionRisk`` call and already carries the signed
convention this project uses. The pool's own settlement currency is not
passed down: Binance offers exactly one ``usdt-m`` pool today (CLAUDE.md's
open risks note — COIN-M is reachable but not in the ``Currency`` enum, so
the futures adapter declares ``usdt-m`` only), and that one pool IS the whole
account this call reads. A second Binance USDⓈ-M pool over a different
settlement currency would need this reader taught to filter by
``marginAsset``, which nothing here does yet because nothing configures it.
"""

from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenuePositionReadError,
)
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
)


class BinanceVenuePositionReader:
    """Implements ``VenuePositionReaderPort`` for the Binance ``usdt-m`` pool."""

    exchange = "binance"
    venues = frozenset({"usdt-m"})

    def __init__(self, client: BinanceReadOnlyClient) -> None:
        self._client = client

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        try:
            positions = await self._client.open_positions()
        except BinanceApiError as exc:
            raise VenuePositionReadError(
                f"Binance position read failed for pool {pool}: {exc}"
            ) from exc

        return [
            VenuePosition(position.symbol, position.signed_size) for position in positions
        ]
