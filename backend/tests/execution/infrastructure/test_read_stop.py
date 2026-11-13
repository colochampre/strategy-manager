"""``ExchangePort.read_stop``: what became of a stop that was found resting
(subscriber-safety SS.7).

Bybit carries the stop on the opening order, so its stop is found again by the opening's own
id, and a stop that no longer rests is looked up by the ORDER the venue gave it, whose
executions are the stop's fills. Binance places the stop as an algo order of its own, read
back by ``clientAlgoId``: ``NEW`` rests, ``FINISHED`` names the order it created and its
fills come from ``userTrades``, and any other end means it is gone. A failure whose outcome
is unknown propagates, so the stop stays ``RESTING`` and the next tick asks again.

The symbol wears a different spelling on each side of the boundary: the stop records
TradingView's ``DOGEUSDT.P`` and the venue is asked for ``DOGEUSDT``.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.execution.application.ports import (
    ExchangeError,
    StopFired,
    StopNotResting,
    StopRests,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_exchange import PionexExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
)
from strategy_manager.shared.infrastructure.binance.errors import (
    BinanceApiError,
    BinanceOrderNotFound,
)
from strategy_manager.shared.infrastructure.binance.trade_client import BinanceAlgoOrder
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitExecution
from tests.execution.infrastructure import test_binance_futures_exchange as binance_tests
from tests.execution.infrastructure import test_bybit_futures_exchange as bybit_tests

ALERT_SYMBOL = "DOGEUSDT.P"
VENUE_SYMBOL = "DOGEUSDT"
OPENING_CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
CLIENT_STOP_ID = "9b2f4c1e-6d3a-4f7b-8a15-2c9e0d4b7a61"


def _stop(
    *, venue_stop_id: str | None = "STOP-1", client_stop_id: str | None = None
) -> ProtectiveStop:
    return ProtectiveStop(
        id=uuid4(),
        execution_attempt_id=uuid4(),
        allocation_id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        symbol=ALERT_SYMBOL,
        position_side=PositionSide.LONG,
        stop_loss_pct=Decimal("10"),
        trigger_price=Decimal("0.0597"),
        status=StopStatus.RESTING,
        venue_stop_id=venue_stop_id,
        client_stop_id=client_stop_id,
    )


# ---- Bybit ----------------------------------------------------------------------------


def _bybit_execution(exec_id: str = "EX-1", qty: str = "76") -> BybitExecution:
    return BybitExecution(
        exec_id=exec_id,
        order_id="STOP-1",
        order_link_id="",
        symbol=VENUE_SYMBOL,
        side="Sell",
        price=Decimal("0.0597"),
        qty=Decimal(qty),
        fee=Decimal("0.0025"),
        fee_currency="USDT",
        exec_time_ms=1787762883000,
    )


async def test_a_bybit_stop_still_held_rests_and_its_executions_are_not_asked_for() -> None:
    client = bybit_tests.FakeTradeClient(resting_stop="STOP-1")

    reading = await bybit_tests._adapter(client).read_stop(_stop(), OPENING_CLIENT_ORDER_ID)

    assert reading == StopRests()
    assert client.stop_lookups == [(VENUE_SYMBOL, OPENING_CLIENT_ORDER_ID)]
    assert client.order_fill_reads == []


async def test_a_bybit_stop_that_no_longer_rests_and_executed_has_fired() -> None:
    client = bybit_tests.FakeTradeClient(
        resting_stop=None,
        stop_executions=[_bybit_execution("EX-1", "46"), _bybit_execution("EX-2", "30")],
    )

    reading = await bybit_tests._adapter(client).read_stop(_stop(), OPENING_CLIENT_ORDER_ID)

    assert client.order_fill_reads == [(VENUE_SYMBOL, "STOP-1")]
    assert isinstance(reading, StopFired)
    assert reading.exchange_order_id == "STOP-1"
    booked = [
        (f.exchange_fill_id, f.quantity, f.price, f.fee, f.fee_currency) for f in reading.fills
    ]
    assert booked == [
        ("EX-1", Decimal("46"), Decimal("0.0597"), Decimal("0.0025"), "USDT"),
        ("EX-2", Decimal("30"), Decimal("0.0597"), Decimal("0.0025"), "USDT"),
    ]
    assert all(isinstance(fill, Fill) for fill in reading.fills)


async def test_a_bybit_stop_that_no_longer_rests_and_never_executed_is_not_resting() -> None:
    client = bybit_tests.FakeTradeClient(resting_stop=None, stop_executions=[])

    reading = await bybit_tests._adapter(client).read_stop(_stop(), OPENING_CLIENT_ORDER_ID)

    assert reading == StopNotResting()
    assert client.order_fill_reads == [(VENUE_SYMBOL, "STOP-1")]


async def test_a_bybit_stop_with_no_recorded_venue_id_cannot_be_looked_up() -> None:
    client = bybit_tests.FakeTradeClient(resting_stop=None)

    with pytest.raises(ExchangeError, match="no venue stop id"):
        await bybit_tests._adapter(client).read_stop(
            _stop(venue_stop_id=None), OPENING_CLIENT_ORDER_ID
        )
    assert client.order_fill_reads == []


@pytest.mark.parametrize(
    "failure",
    [
        BybitApiError("server timeout", code="10000"),
        BybitApiError("connection reset"),
        BybitApiError("gateway", http_status=502),
        BybitApiError("throttled", http_status=429),
    ],
)
@pytest.mark.parametrize("failing_read", ["stop", "executions"])
async def test_an_ambiguous_bybit_failure_propagates_so_the_stop_stays_resting(
    failure: BybitApiError, failing_read: str
) -> None:
    client = bybit_tests.FakeTradeClient(
        resting_stop=None,
        stop_raises=failure if failing_read == "stop" else None,
        stop_executions_raise=failure if failing_read == "executions" else None,
    )

    with pytest.raises(BybitApiError) as caught:
        await bybit_tests._adapter(client).read_stop(_stop(), OPENING_CLIENT_ORDER_ID)

    assert caught.value is failure
    assert not isinstance(caught.value, ExchangeError)


@pytest.mark.parametrize("failing_read", ["stop", "executions"])
async def test_a_definitive_bybit_refusal_is_an_exchange_error(failing_read: str) -> None:
    refusal = BybitApiError("no permission", code="10005")
    client = bybit_tests.FakeTradeClient(
        resting_stop=None,
        stop_raises=refusal if failing_read == "stop" else None,
        stop_executions_raise=refusal if failing_read == "executions" else None,
    )

    with pytest.raises(ExchangeError):
        await bybit_tests._adapter(client).read_stop(_stop(), OPENING_CLIENT_ORDER_ID)


# ---- Binance --------------------------------------------------------------------------


def _binance_stop() -> ProtectiveStop:
    return _stop(venue_stop_id="3000000123456", client_stop_id=CLIENT_STOP_ID)


def _algo(status: str | None, actual_order_id: int | None = None) -> BinanceAlgoOrder:
    return BinanceAlgoOrder(
        algo_id=3000000123456,
        client_algo_id=CLIENT_STOP_ID,
        status=status,
        actual_order_id=actual_order_id,
    )


async def test_a_new_binance_stop_rests_and_is_read_by_its_client_id_alone() -> None:
    client = binance_tests.StopClient(algo_answers=[_algo("NEW")])

    reading = await binance_tests._stop_adapter(client).read_stop(
        _binance_stop(), OPENING_CLIENT_ORDER_ID
    )

    assert reading == StopRests()
    assert client.algo_reads == [CLIENT_STOP_ID]
    assert client.fill_reads == []


@pytest.mark.parametrize("status", ["TRIGGERING", "TRIGGERED", None])
async def test_a_binance_stop_in_any_other_live_status_is_read_as_still_resting(
    status: str | None,
) -> None:
    """The stop is in the middle of firing: the next tick reads it again."""
    client = binance_tests.StopClient(algo_answers=[_algo(status)])

    reading = await binance_tests._stop_adapter(client).read_stop(
        _binance_stop(), OPENING_CLIENT_ORDER_ID
    )

    assert reading == StopRests()
    assert client.fill_reads == []


async def test_a_finished_binance_stop_fired_and_its_fills_come_from_the_order_it_made() -> None:
    execution = binance_tests._execution(
        order_id=105975543111, trade_id=77, qty=Decimal("76"), side="SELL"
    )
    client = binance_tests.StopClient(
        algo_answers=[_algo("FINISHED", actual_order_id=105975543111)],
        executions=[execution],
    )

    reading = await binance_tests._stop_adapter(client).read_stop(
        _binance_stop(), OPENING_CLIENT_ORDER_ID
    )

    assert client.fill_reads == [(VENUE_SYMBOL, 105975543111)]
    assert isinstance(reading, StopFired)
    assert reading.exchange_order_id == "105975543111"
    [fill] = reading.fills
    assert (fill.exchange_order_id, fill.exchange_fill_id, fill.quantity) == (
        "105975543111",
        "77",
        Decimal("76"),
    )


async def test_a_finished_binance_stop_whose_fills_are_not_published_has_fired_with_none() -> None:
    """The watcher waits: an empty list is "not published yet", never "did not fire"."""
    client = binance_tests.StopClient(
        algo_answers=[_algo("FINISHED", actual_order_id=105975543111)], executions=[]
    )

    reading = await binance_tests._stop_adapter(client).read_stop(
        _binance_stop(), OPENING_CLIENT_ORDER_ID
    )

    assert reading == StopFired(exchange_order_id="105975543111", fills=[])


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELED", "REJECTED"])
async def test_an_expired_cancelled_or_rejected_binance_stop_is_not_resting(
    status: str,
) -> None:
    client = binance_tests.StopClient(algo_answers=[_algo(status)])

    reading = await binance_tests._stop_adapter(client).read_stop(
        _binance_stop(), OPENING_CLIENT_ORDER_ID
    )

    assert reading == StopNotResting()
    assert client.fill_reads == []


async def test_a_finished_binance_stop_that_names_no_order_cannot_be_read() -> None:
    """Reading it as gone would leave a fired stop's fills unbooked."""
    client = binance_tests.StopClient(algo_answers=[_algo("FINISHED", actual_order_id=None)])

    with pytest.raises(ExchangeError, match="actualOrderId"):
        await binance_tests._stop_adapter(client).read_stop(
            _binance_stop(), OPENING_CLIENT_ORDER_ID
        )


async def test_a_binance_stop_the_venue_does_not_know_is_not_read_as_gone() -> None:
    """-2013 is also how a stop answers for a moment after it is placed, so the
    watcher never believes it: the stop stays RESTING and is read again."""
    missing = BinanceOrderNotFound("no such algo order")
    client = binance_tests.StopClient(algo_answers=[missing])
    sleep = binance_tests.RecordingSleep()

    with pytest.raises(BinanceOrderNotFound) as caught:
        await binance_tests._stop_adapter(client, sleep).read_stop(
            _binance_stop(), OPENING_CLIENT_ORDER_ID
        )

    assert caught.value is missing
    assert sleep.waits == []


@pytest.mark.parametrize(
    ("code", "http_status"),
    [("-1007", 400), ("-1008", 503), ("-1003", 429), ("-1000", 408)],
)
@pytest.mark.parametrize("failing_read", ["algo", "fills"])
async def test_an_ambiguous_binance_failure_propagates_so_the_stop_stays_resting(
    code: str, http_status: int, failing_read: str
) -> None:
    error = BinanceApiError("Send status unknown", code=code, http_status=http_status)

    class Client(binance_tests.StopClient):
        async def fills_for(self, *, symbol: str, order_id: int) -> list:  # type: ignore[type-arg]
            raise error

    client = Client(
        algo_answers=[error if failing_read == "algo" else _algo("FINISHED", 105975543111)]
    )

    with pytest.raises(BinanceApiError) as caught:
        await binance_tests._stop_adapter(client).read_stop(
            _binance_stop(), OPENING_CLIENT_ORDER_ID
        )

    assert caught.value is error


async def test_a_definitive_binance_refusal_of_the_read_is_an_exchange_error() -> None:
    client = binance_tests.StopClient(
        algo_answers=[
            BinanceApiError("Invalid API-key, IP, or permissions", code="-2015", http_status=401)
        ]
    )

    with pytest.raises(ExchangeError, match="-2015"):
        await binance_tests._stop_adapter(client).read_stop(
            _binance_stop(), OPENING_CLIENT_ORDER_ID
        )


async def test_a_binance_stop_with_no_client_id_cannot_be_read() -> None:
    client = binance_tests.StopClient()

    with pytest.raises(ExchangeError, match="no client stop id"):
        await binance_tests._stop_adapter(client).read_stop(
            _stop(client_stop_id=None), OPENING_CLIENT_ORDER_ID
        )
    assert client.algo_reads == []


# ---- the adapters with no stop of their own to read ---------------------------------


@pytest.mark.parametrize(
    "adapter", [PionexExchangeAdapter, PionexFuturesExchangeAdapter, FakeExchangeAdapter]
)
async def test_an_adapter_with_no_stop_of_its_own_refuses_to_read_one(adapter: type) -> None:
    instance = adapter.__new__(adapter)

    with pytest.raises(ExchangeError):
        await instance.read_stop(_stop(), OPENING_CLIENT_ORDER_ID)
