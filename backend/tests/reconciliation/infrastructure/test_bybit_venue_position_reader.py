"""``BybitVenuePositionReader`` — a thin translation from Bybit's own
``Position`` read model into the domain's ``VenuePosition``, plus the one
exception ``ScanPools`` is allowed to swallow per pool.
"""

from decimal import Decimal

import pytest

from strategy_manager.reconciliation.application.ports import VenuePositionReadError
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.reconciliation.infrastructure.bybit_venue_position_reader import (
    BybitVenuePositionReader,
)
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import Position

POOL = ("bybit", "usdt-m", "USDT")


def _position(
    symbol: str = "BTCUSDT",
    side: str = "Buy",
    size: str = "0.5",
) -> Position:
    return Position(
        symbol=symbol,
        side=side,
        size=Decimal(size),
        avg_price=Decimal("60000"),
        leverage=Decimal("3"),
        position_idx=0,
        unrealised_pnl=Decimal("10"),
        liq_price=Decimal("40000"),
    )


class FakeBybitClient:
    def __init__(
        self,
        positions: list[Position] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._positions = positions or []
        self._raises = raises
        self.settle_coins: list[str] = []

    async def positions(self, settle_coin: str = "USDT") -> list[Position]:
        self.settle_coins.append(settle_coin)
        if self._raises is not None:
            raise self._raises
        return self._positions


async def test_reads_the_pools_own_settlement_currency() -> None:
    client = FakeBybitClient([_position()])
    reader = BybitVenuePositionReader(client)  # type: ignore[arg-type]

    await reader.open_positions(("bybit", "usdt-m", "USDC"))

    assert client.settle_coins == ["USDC"]


async def test_translates_a_long_position_to_a_positive_net_base() -> None:
    client = FakeBybitClient([_position(symbol="BTCUSDT", side="Buy", size="0.5")])
    reader = BybitVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert positions == [VenuePosition("BTCUSDT", Decimal("0.5"))]


async def test_translates_a_short_position_to_a_negative_net_base() -> None:
    """``Position.signed_size`` already normalises the sign; this reader must
    not reimplement it."""
    client = FakeBybitClient([_position(symbol="ETHUSDT", side="Sell", size="2")])
    reader = BybitVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert positions[0].symbol == "ETHUSDT"
    assert positions[0].net_base == Decimal("-2")


async def test_reads_every_symbol_the_pool_reports_in_one_call() -> None:
    client = FakeBybitClient(
        [_position(symbol="BTCUSDT"), _position(symbol="ETHUSDT", side="Sell")]
    )
    reader = BybitVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert {p.symbol for p in positions} == {"BTCUSDT", "ETHUSDT"}
    assert len(client.settle_coins) == 1


async def test_a_client_failure_is_translated_to_venue_position_read_error() -> None:
    """The only exception ``ScanPools`` is allowed to swallow per pool."""
    client = FakeBybitClient(raises=BybitApiError("rate limited"))
    reader = BybitVenuePositionReader(client)  # type: ignore[arg-type]

    with pytest.raises(VenuePositionReadError, match="rate limited"):
        await reader.open_positions(POOL)


async def test_the_reader_declares_its_own_exchange_and_venues() -> None:
    """Consulted by the registry at construction time to build the routing
    table -- mirrors ``ExchangePort.exchange``/``.venues`` exactly."""
    reader = BybitVenuePositionReader(FakeBybitClient())  # type: ignore[arg-type]

    assert reader.exchange == "bybit"
    assert reader.venues == frozenset({"usdt-m"})
