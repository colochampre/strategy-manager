"""Implements ``VenuePositionReaderPort`` over the read-only Bybit client.

A thin wrapper, deliberately: ``BybitReadOnlyClient.positions`` already answers
a WHOLE pool in one ``/v5/position/list`` call, and ``Position.signed_size``
already normalises Buy/Sell into this project's own signed convention. There
is nothing left for this class to compute -- only to translate a venue-shaped
``Position`` into the domain's own ``VenuePosition`` and to translate a
transport failure into the ONE exception ``ScanPools`` is allowed to swallow
per pool.
"""

from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenuePositionReadError,
)
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient


class BybitVenuePositionReader:
    """Implements ``VenuePositionReaderPort`` for the Bybit ``usdt-m`` pool."""

    exchange = "bybit"
    venues = frozenset({"usdt-m"})

    def __init__(self, client: BybitReadOnlyClient) -> None:
        self._client = client

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        _, _, settlement_currency = pool
        try:
            positions = await self._client.positions(settle_coin=settlement_currency)
        except BybitApiError as exc:
            raise VenuePositionReadError(
                f"Bybit position read failed for pool {pool}: {exc}"
            ) from exc

        return [
            VenuePosition(position.symbol, position.signed_size) for position in positions
        ]
