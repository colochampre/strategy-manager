"""``venue_support`` — reporting which enabled pools no registered adapter can
trade.

Note what is NOT here: an assertion. This module reports and the startup path
logs; the refusal lives in ``ProcessSignalHandler``, costing the one signal
that would actually be mispriced.

Refusing at startup was the first attempt and it was disproportionate. A
``coin-m`` pool that no strategy trades would have stopped the worker outright,
taking working spot trading down with it over a configuration nobody was using.

The question is asked per POOL, ``(exchange, venue)``: once Binance and Bybit
both offer ``usdt-m``, a venue on its own no longer identifies an adapter.
"""

from decimal import Decimal

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.execution.infrastructure.venue_support import (
    describe_unserved,
    pool_route,
    unserved_pools,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

BYBIT_FUTURES = (Exchange.BYBIT.value, Venue.USDT_M.value)
BINANCE_FUTURES = (Exchange.BINANCE.value, Venue.USDT_M.value)
PIONEX_SPOT = (Exchange.PIONEX.value, Venue.SPOT.value)


def _pool(
    exchange: Exchange,
    venue: Venue,
    currency: Currency = Currency.USDT,
) -> PoolConfig:
    return PoolConfig(
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        min_order_size=Decimal("10"),
    )


def test_a_pool_whose_adapter_is_registered_is_not_reported() -> None:
    served = frozenset({BYBIT_FUTURES})

    assert unserved_pools(served=served, pools=[_pool(Exchange.BYBIT, Venue.USDT_M)]) == []


def test_the_same_venue_on_an_unregistered_exchange_is_reported() -> None:
    """THE case this key exists for. Bybit's usdt-m adapter does not serve
    Binance's usdt-m pool: the venue matches and the money does not."""
    served = frozenset({BYBIT_FUTURES})

    unserved = unserved_pools(served=served, pools=[_pool(Exchange.BINANCE, Venue.USDT_M)])

    assert unserved == ["binance/usdt-m"]


def test_every_unserved_pool_is_named_once_and_sorted() -> None:
    served = frozenset({BYBIT_FUTURES})
    pools = [
        _pool(Exchange.BYBIT, Venue.USDT_M),
        _pool(Exchange.BINANCE, Venue.USDT_M),
        _pool(Exchange.PIONEX, Venue.SPOT),
        _pool(Exchange.PIONEX, Venue.COIN_M, Currency.BTC),
    ]

    assert unserved_pools(served=served, pools=pools) == [
        "binance/usdt-m",
        "pionex/coin-m",
        "pionex/spot",
    ]


def test_nothing_is_unserved_when_every_pool_has_an_adapter() -> None:
    served = frozenset({BYBIT_FUTURES, PIONEX_SPOT})
    pools = [_pool(Exchange.BYBIT, Venue.USDT_M), _pool(Exchange.PIONEX, Venue.SPOT)]

    assert unserved_pools(served=served, pools=pools) == []


def test_no_pools_at_all_reports_nothing() -> None:
    assert unserved_pools(served=frozenset({BYBIT_FUTURES}), pools=[]) == []


def test_pool_route_is_the_pair_the_registry_is_keyed_by() -> None:
    assert pool_route(_pool(Exchange.BINANCE, Venue.USDT_M)) == BINANCE_FUTURES


def test_the_warning_names_both_halves_of_the_mismatch() -> None:
    """The operator's two remedies — disable those pools, or register an
    adapter that serves them — both need to know which pool is which."""
    message = describe_unserved(
        served=frozenset({BYBIT_FUTURES}),
        by="BybitFuturesExchangeAdapter",
        unserved=["binance/usdt-m"],
    )

    assert "bybit/usdt-m" in message
    assert "binance/usdt-m" in message
    assert "BybitFuturesExchangeAdapter" in message
    assert "Disable those pools" in message


def test_the_warning_says_signals_are_refused_not_that_startup_stops() -> None:
    """The wording matters operationally. An operator who reads this as 'the
    worker will not start' will go disable pools under time pressure that
    nothing was blocking."""
    message = describe_unserved(
        served=frozenset({BYBIT_FUTURES}), by="BybitFuturesExchangeAdapter",
        unserved=["binance/usdt-m"],
    )

    assert "refused rather than executed against the wrong wallet" in message
    assert "Refusing to start" not in message


def test_a_registry_serving_nothing_says_so() -> None:
    message = describe_unserved(served=frozenset(), by="nothing", unserved=["bybit/usdt-m"])

    assert "trades nothing" in message
