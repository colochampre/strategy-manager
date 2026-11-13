"""A reduce-only close the venue refuses because the position is flat (subscriber-safety SS.7).

When a protective stop fires while a close is in flight, the venue refuses the reduce-only
close because there is nothing left to reduce. That refusal is ``PositionAlreadyFlat``, a
definitive ``ExchangeError`` that ``ClosePosition`` ends ``ALREADY_FLAT`` with a WARNING.

The codes are an *assumption*, unverified live: Bybit ``110017`` and Binance ``-2022``. They
are read only on a reduce-only order: an opening refused with the same code is an ordinary
refusal, and a code that is not one of the two stays the plain ``ExchangeError`` it always
was.
"""

import pytest

from strategy_manager.execution.application.ports import ExchangeError, PositionAlreadyFlat
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from tests.execution.infrastructure import test_binance_futures_exchange as binance_tests
from tests.execution.infrastructure import test_bybit_futures_exchange as bybit_tests

# ---- Bybit ----------------------------------------------------------------------------


async def test_a_bybit_reduce_only_close_refused_for_a_flat_position_is_already_flat() -> None:
    failure = BybitApiError("current position is zero", code="110017")
    client = bybit_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(PositionAlreadyFlat) as caught:
        await bybit_tests._adapter(client).place(bybit_tests._order(reduce_only=True))

    assert "110017" in str(caught.value) or "current position is zero" in str(caught.value)
    assert isinstance(caught.value, ExchangeError)
    assert caught.value.__cause__ is failure


async def test_a_bybit_opening_refused_with_the_same_code_is_an_ordinary_refusal() -> None:
    client = bybit_tests.FakeTradeClient(place_raises=BybitApiError("no", code="110017"))

    with pytest.raises(ExchangeError) as caught:
        await bybit_tests._adapter(client).place(bybit_tests._order(reduce_only=False))

    assert not isinstance(caught.value, PositionAlreadyFlat)


async def test_a_bybit_reduce_only_close_refused_for_another_reason_stays_a_plain_refusal() -> None:
    client = bybit_tests.FakeTradeClient(place_raises=BybitApiError("no", code="110007"))

    with pytest.raises(ExchangeError) as caught:
        await bybit_tests._adapter(client).place(bybit_tests._order(reduce_only=True))

    assert not isinstance(caught.value, PositionAlreadyFlat)


async def test_a_bybit_unknown_outcome_is_never_read_as_flat() -> None:
    """A timeout says nothing about the position: it propagates for the job to retry."""
    failure = BybitApiError("server timeout", code="10000")
    client = bybit_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(BybitApiError) as caught:
        await bybit_tests._adapter(client).place(bybit_tests._order(reduce_only=True))

    assert caught.value is failure
    assert not isinstance(caught.value, ExchangeError)


# ---- Binance --------------------------------------------------------------------------


async def test_a_binance_reduce_only_close_refused_for_a_flat_position_is_already_flat() -> None:
    failure = BinanceApiError("ReduceOnly Order is rejected", code="-2022", http_status=400)
    client = binance_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(PositionAlreadyFlat) as caught:
        await binance_tests._adapter(client).place(binance_tests._order(reduce_only=True))

    assert isinstance(caught.value, ExchangeError)
    assert caught.value.__cause__ is failure


async def test_a_binance_opening_refused_with_the_same_code_is_an_ordinary_refusal() -> None:
    failure = BinanceApiError("ReduceOnly Order is rejected", code="-2022", http_status=400)
    client = binance_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(ExchangeError) as caught:
        await binance_tests._adapter(client).place(binance_tests._order(reduce_only=False))

    assert not isinstance(caught.value, PositionAlreadyFlat)


async def test_a_binance_reduce_only_close_refused_for_another_reason_stays_plain() -> None:
    failure = BinanceApiError("Order would immediately trigger", code="-2021", http_status=400)
    client = binance_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(ExchangeError) as caught:
        await binance_tests._adapter(client).place(binance_tests._order(reduce_only=True))

    assert not isinstance(caught.value, PositionAlreadyFlat)


async def test_a_binance_unknown_outcome_is_never_read_as_flat() -> None:
    failure = BinanceApiError("Send status unknown", code="-1007", http_status=500)
    client = binance_tests.FakeTradeClient(place_raises=failure)

    with pytest.raises(BinanceApiError) as caught:
        await binance_tests._adapter(client).place(binance_tests._order(reduce_only=True))

    assert caught.value is failure
    assert not isinstance(caught.value, ExchangeError)
