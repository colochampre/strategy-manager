"""What an adapter that places no stop after the fill says about it (subscriber-safety SS.6).

Binance has no stop on the opening order, so it places one once the fills are recorded and
its adapter implements the three calls below for real. Every other adapter inherits this:
Bybit carries the stop on the opening order, Pionex spot is outside the protective stop
(D9), Pionex futures cannot run at all, and the simulated exchange places nothing.

The calls refuse rather than answer. They are never asked, because ``PlaceOrder`` writes the
row that asks for them only for an adapter whose ``places_stop_after_fill`` is true, and a
stop invented for a venue that holds none is the failure this prevents.
"""

from decimal import Decimal

from strategy_manager.execution.application.ports import ExchangeError, RestingStop
from strategy_manager.execution.domain.protective_stop import PositionSide


class NoAfterFillStop:
    places_stop_after_fill = False

    async def stop_trigger_price(
        self,
        symbol: str,
        position_side: PositionSide,
        entry: Decimal,
        stop_loss_pct: Decimal,
    ) -> Decimal:
        raise ExchangeError("this adapter places no stop after the fill")

    async def place_stop(
        self,
        symbol: str,
        position_side: PositionSide,
        trigger_price: Decimal,
        client_stop_id: str,
    ) -> str:
        raise ExchangeError("this adapter places no stop after the fill")

    async def find_stop(self, symbol: str, client_stop_id: str) -> RestingStop | None:
        raise ExchangeError("this adapter places no stop after the fill")
