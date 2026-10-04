"""The production composition root builds the simulated exchanges (decision 45;
design §§ E and J; spec: trade-execution § "An Exchange With No Simulated Fee
Rate Is Not Served In Dry Run" and § "Simulated Pricing Is Visible In The Log").

``main.build_worker_runner`` is the real thing: only the exchange class is
wrapped by a spy that records what was built, and the log is read through
``caplog``. Building a runner opens no connection (the session factory is never
used) and no test needs a credential or the network (rule 1): ``DRY_RUN`` is on
everywhere except the one test that proves it off builds nothing.
"""

import logging
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.simulated_fee_rates import (
    SIMULATED_TAKER_FEE_RATES,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

MAIN_LOGGER = "strategy_manager.main"


def _pool(exchange: Exchange, venue: Venue) -> PoolConfig:
    return PoolConfig(
        exchange=exchange,
        venue=venue,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("10"),
    )


BYBIT_POOL = _pool(Exchange.BYBIT, Venue.USDT_M)
PIONEX_POOL = _pool(Exchange.PIONEX, Venue.SPOT)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[FakeExchangeAdapter]:
    """Every ``FakeExchangeAdapter`` the composition root builds, in order. The
    spy IS the production class: it only remembers each instance."""
    instances: list[FakeExchangeAdapter] = []

    class SpyFakeExchange(FakeExchangeAdapter):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(main, "FakeExchangeAdapter", SpyFakeExchange)
    return instances


def _build_worker(
    monkeypatch: pytest.MonkeyPatch,
    pools: list[PoolConfig],
    *,
    dry_run: bool = True,
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", dry_run)
    main.build_worker_runner(pools, session_factory_override=async_sessionmaker())


def _simulated_lines(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == MAIN_LOGGER
        and record.levelno == level
        and "simulated exchange" in record.getMessage()
    ]


def test_a_dry_run_worker_logs_one_info_naming_each_exchange_and_its_taker_rate(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=MAIN_LOGGER)

    _build_worker(monkeypatch, [BYBIT_POOL])

    lines = _simulated_lines(caplog, logging.INFO)
    assert len(lines) == 1
    text = lines[0].getMessage()
    assert "prices each fill at its alert's price" in text
    assert "bybit=0.00055" in text
    assert "binance=0.0005" in text


def test_a_dry_run_worker_logs_the_rates_it_actually_built_the_exchanges_with(
    monkeypatch: pytest.MonkeyPatch, built: list[FakeExchangeAdapter]
) -> None:
    """Production wiring passes the table's rate by key: not zero, not a
    default (a fee of zero is never charged because nobody decided one)."""
    _build_worker(monkeypatch, [BYBIT_POOL])

    rates = {fake.exchange: fake.fee_rate for fake in built}
    assert rates == {"bybit": Decimal("0.00055"), "binance": Decimal("0.0005")}
    assert rates == dict(SIMULATED_TAKER_FEE_RATES)
    assert all(fake.fixed_fill_price is None for fake in built)


def test_a_dry_run_worker_logs_no_warning_about_a_fixed_price(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=MAIN_LOGGER)

    _build_worker(monkeypatch, [BYBIT_POOL])

    assert [r for r in caplog.records if "fixed" in r.getMessage()] == []
    assert _simulated_lines(caplog, logging.WARNING) == []


def test_a_simulated_exchange_built_with_a_fixed_price_is_one_startup_warning_naming_the_exchange_and_the_price(  # noqa: E501
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The startup-line function takes the instances. Production never passes
    one built with a fixed price; this is what makes a later edit of
    ``main.py`` visible in the journal."""
    caplog.set_level(logging.INFO, logger=MAIN_LOGGER)
    fixed = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("1"), fee_rate=Decimal("0.00055")
    )
    alert_priced = FakeExchangeAdapter(exchange="binance", fee_rate=Decimal("0.0005"))

    main.log_simulated_exchange_startup({"bybit": fixed, "binance": alert_priced})

    warnings = _simulated_lines(caplog, logging.WARNING)
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert "'bybit'" in text
    assert "fixed price of 1" in text
    # The exchange that is alert-priced is still reported, at INFO, with its rate.
    [info] = _simulated_lines(caplog, logging.INFO)
    assert "binance=0.0005" in info.getMessage()
    assert "bybit" not in info.getMessage()


def test_an_exchange_with_a_pool_and_no_rate_has_no_simulated_exchange_and_two_warnings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    built: list[FakeExchangeAdapter],
) -> None:
    caplog.set_level(logging.INFO, logger=MAIN_LOGGER)

    _build_worker(monkeypatch, [BYBIT_POOL, PIONEX_POOL])  # the worker still builds

    assert sorted(fake.exchange for fake in built) == ["binance", "bybit"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    unserved = [w for w in warnings if "enabled capital pools exist on" in w]
    assert len(unserved) == 1
    assert "pionex/spot" in unserved[0]
    reasons = [w for w in warnings if "no simulated taker fee rate is defined for 'pionex'" in w]
    assert len(reasons) == 1
    # Pionex is not named by the startup INFO: it has no simulated exchange.
    [info] = _simulated_lines(caplog, logging.INFO)
    assert "pionex" not in info.getMessage()


def test_bybit_and_binance_have_a_simulated_exchange_even_when_no_pool_names_them(
    monkeypatch: pytest.MonkeyPatch, built: list[FakeExchangeAdapter]
) -> None:
    """Decision 21 auto-enables a futures pool for either exchange at any
    moment, so a deployment that started with neither still needs a rehearsal
    adapter ready (binding requirement 6)."""
    _build_worker(monkeypatch, [])

    assert sorted(fake.exchange for fake in built) == ["binance", "bybit"]


def test_with_dry_run_false_no_simulated_exchange_is_built_and_no_simulated_line_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    built: list[FakeExchangeAdapter],
) -> None:
    """The real adapters' side is proven on the wire in
    ``test_real_adapters_ignore_reference_price``. Here: a live process builds no
    rehearsal exchange and says nothing about one."""
    caplog.set_level(logging.INFO, logger=MAIN_LOGGER)

    _build_worker(monkeypatch, [BYBIT_POOL, PIONEX_POOL], dry_run=False)

    assert built == []
    assert [r for r in caplog.records if "simulated" in r.getMessage()] == []
