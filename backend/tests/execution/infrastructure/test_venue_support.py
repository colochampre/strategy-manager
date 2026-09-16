"""``venue_support`` — reporting which enabled pools the registered adapter
cannot trade.

Note what is NOT here: an assertion. This module reports and the startup path
logs; the refusal lives in ``ProcessSignalHandler``, costing the one signal
that would actually be mispriced.

Refusing at startup was the first attempt and it was disproportionate. A
``coin-m`` pool that no strategy trades would have stopped the worker outright,
taking working spot trading down with it over a configuration nobody was using.
"""

from decimal import Decimal

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_exchange import (
    PionexExchangeAdapter,
)
from strategy_manager.execution.infrastructure.venue_support import (
    describe_unserved,
    describe_untradable,
    unserved_pool_venues,
    untradable_pool_venues,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


def _pool(venue: Venue, currency: Currency = Currency.USDT) -> PoolConfig:
    return PoolConfig(
        exchange=Exchange.BYBIT,
        venue=venue,
        settlement_currency=currency,
        min_order_size=Decimal("10"),
    )


def test_a_spot_pool_against_the_spot_adapter_is_tradable() -> None:
    assert untradable_pool_venues(exchange=PionexExchangeAdapter, pools=[_pool(Venue.SPOT)]) == []


def test_futures_pools_against_the_spot_adapter_are_reported() -> None:
    """PionexTradeClient speaks /api/v1/, which is spot. Pionex's futures API
    is /uapi/v1/ and needs its own adapter."""
    untradable = untradable_pool_venues(
        exchange=PionexExchangeAdapter,
        pools=[
            _pool(Venue.SPOT),
            _pool(Venue.USDT_M),
            _pool(Venue.COIN_M, Currency.BTC),
        ],
    )

    assert untradable == ["coin-m", "usdt-m"]


def test_the_warning_names_both_halves_of_the_mismatch() -> None:
    """The operator's two remedies — disable those pools, or register an
    adapter that serves them — both need to know which venue is which."""
    message = describe_untradable(exchange=PionexExchangeAdapter, untradable=["coin-m", "usdt-m"])

    assert "PionexExchangeAdapter" in message
    assert "trades spot" in message
    assert "coin-m, usdt-m" in message
    assert "Disable those pools" in message


def test_the_warning_says_signals_are_refused_not_that_startup_stops() -> None:
    """The wording matters operationally. An operator who reads this as 'the
    worker will not start' will go disable pools under time pressure that
    nothing was blocking."""
    message = describe_untradable(exchange=PionexExchangeAdapter, untradable=["usdt-m"])

    assert "refused" in message
    assert "Refusing to start" not in message


def test_the_fake_adapter_reports_nothing_untradable() -> None:
    """Not a loophole: DRY_RUN is what stands between the fake and a real
    exchange, and a developer running every pool against it reaches none."""
    assert (
        untradable_pool_venues(
            exchange=FakeExchangeAdapter,
            pools=[
                _pool(Venue.SPOT),
                _pool(Venue.USDT_M),
                _pool(Venue.COIN_M, Currency.BTC),
            ],
        )
        == []
    )


def test_it_accepts_an_instance_as_well_as_a_class() -> None:
    """The live adapter is built per job — it needs a decrypted credential and
    an open socket — so the composition root reads the class."""
    instance = PionexExchangeAdapter(None)  # type: ignore[arg-type]

    assert untradable_pool_venues(exchange=instance, pools=[_pool(Venue.SPOT)]) == []
    assert untradable_pool_venues(exchange=instance, pools=[_pool(Venue.USDT_M)]) == ["usdt-m"]


def test_no_pools_at_all_reports_nothing() -> None:
    assert untradable_pool_venues(exchange=PionexExchangeAdapter, pools=[]) == []


def test_the_union_across_adapters_is_what_counts_as_unserved() -> None:
    """Asking each adapter separately would report every futures pool as
    untradable merely because the spot adapter does not serve it -- noise that
    trains an operator to ignore the one warning that matters."""
    pools = [_pool(Venue.SPOT), _pool(Venue.USDT_M), _pool(Venue.COIN_M, Currency.BTC)]

    unserved = unserved_pool_venues(served=frozenset({"spot", "usdt-m"}), pools=pools)

    assert unserved == ["coin-m"]


def test_nothing_is_unserved_when_every_pool_has_an_adapter() -> None:
    pools = [_pool(Venue.SPOT), _pool(Venue.USDT_M)]

    assert unserved_pool_venues(served=frozenset({"spot", "usdt-m"}), pools=pools) == []


def test_the_union_warning_names_both_halves_of_the_mismatch() -> None:
    message = describe_unserved(
        served=frozenset({"spot", "usdt-m"}),
        by="PionexExchangeAdapter + PionexFuturesExchangeAdapter",
        unserved=["coin-m"],
    )

    assert "spot, usdt-m" in message
    assert "coin-m" in message
    assert "refused rather than executed against the wrong wallet" in message
