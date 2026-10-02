"""The credential-free Binance catalogue: which USDⓈ-M perpetuals a pool may use.

Venue spelling only: every symbol here is Binance's own (``STXUSDT``). The
``market_key`` mapping happens one layer up, where the pool is known.
"""

import logging
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.public_catalogue import (
    BinancePublicCatalogue,
)
from strategy_manager.shared.infrastructure.binance.transport import (
    BinancePublicTransport,
)
from tests.shared.infrastructure.binance.test_futures_rules import (
    AAVE,
    QUARTERLY,
    TRADIFI,
)

LOGGER = "strategy_manager.shared.infrastructure.binance.public_catalogue"

STX: dict[str, Any] = {**AAVE, "symbol": "STXUSDT", "baseAsset": "STX"}
# Quoted in USDT but MARGINED in USDC: it draws on the USDC pool.
USDC_MARGINED: dict[str, Any] = {**AAVE, "symbol": "BTCUSDC", "marginAsset": "USDC"}
SETTLING: dict[str, Any] = {**AAVE, "symbol": "OLDUSDT", "status": "SETTLING"}
PENDING: dict[str, Any] = {**AAVE, "symbol": "NEWUSDT", "status": "PENDING_TRADING"}


def _catalogue(
    response: httpx.Response, recorded: list[httpx.Request] | None = None
) -> BinancePublicCatalogue:
    def handler(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.append(request)
        return response

    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(handler)
    )
    return BinancePublicCatalogue(BinancePublicTransport(http))


def _listing(entries: list[Any]) -> BinancePublicCatalogue:
    return _catalogue(httpx.Response(200, json={"symbols": entries}))


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == level]


def _only(records: list[logging.LogRecord]) -> logging.LogRecord:
    """The one record expected, asserted rather than unpacked so a missing or a
    duplicated line fails on an assertion that names the count."""
    assert len(records) == 1, [r.getMessage() for r in records]
    return records[0]


# --- the filter -------------------------------------------------------------


async def test_tradable_perpetuals_excludes_tradifi_quarterly_and_usdc_margined() -> None:
    catalogue = _listing([AAVE, TRADIFI, QUARTERLY, USDC_MARGINED, STX])

    usdt = await catalogue.tradable_perpetuals("USDT")
    usdc = await catalogue.tradable_perpetuals("USDC")

    assert usdt == ("AAVEUSDT", "STXUSDT")
    assert usdc == ("BTCUSDC",)


async def test_a_perpetual_that_is_not_trading_is_excluded() -> None:
    """Probe P7 saw SETTLING (131) and PENDING_TRADING (1) beside TRADING."""
    kept = await _listing([SETTLING, AAVE, PENDING]).tradable_perpetuals("USDT")

    assert kept == ("AAVEUSDT",)


# --- malformed entries ------------------------------------------------------


async def test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    no_filters = {**AAVE, "symbol": "BADUSDT", "filters": "none"}
    no_symbol = {**AAVE, "filters": []}
    del no_symbol["symbol"]
    entries = [AAVE, no_filters, "not an object", no_symbol, STX]

    symbols = await _listing(entries).tradable_perpetuals("USDT")

    assert symbols == ("AAVEUSDT", "STXUSDT")
    warning = _only(_records(caplog, logging.WARNING))
    message = warning.getMessage()
    assert "3" in message
    assert "BADUSDT" in message
    assert "<no symbol>" in message
    assert _records(caplog, logging.ERROR) == []


async def test_the_warning_names_at_most_ten_symbols(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    broken = [{**AAVE, "symbol": f"BAD{index:02d}USDT", "filters": 1} for index in range(12)]

    await _listing([AAVE, *broken]).tradable_perpetuals("USDT")

    message = _only(_records(caplog, logging.WARNING)).getMessage()
    assert "12" in message
    assert "BAD09USDT" in message
    assert "BAD10USDT" not in message


async def test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A renamed value would otherwise turn every valid symbol into an
    "unknown pair": a wrong message, not a refusal."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    renamed = {**AAVE, "contractType": "PERPETUAL_V2", "status": "LIVE"}

    with pytest.raises(BinanceApiError, match="no tradable perpetual"):
        await _listing([renamed, TRADIFI, QUARTERLY]).tradable_perpetuals("USDT")

    message = _only(_records(caplog, logging.ERROR)).getMessage()
    assert "PERPETUAL_V2" in message
    assert "TRADIFI_PERPETUAL" in message
    assert "CURRENT_QUARTER" in message
    assert "LIVE" in message


async def test_an_empty_listing_is_not_mistaken_for_an_unreadable_one() -> None:
    assert await _listing([]).tradable_perpetuals("USDT") == ()


async def test_http_451_raises_and_is_never_an_empty_listing() -> None:
    """451 is a property of WHERE the request comes from. Reading it as "no
    pairs" would make every save look like a typo."""
    catalogue = _catalogue(httpx.Response(451, json={"msg": "Service unavailable"}))

    with pytest.raises(BinanceApiError, match="HTTP 451") as refused:
        await catalogue.tradable_perpetuals("USDT")

    assert refused.value.http_status == 451


# --- what an operator sees --------------------------------------------------


async def test_a_real_read_logs_one_info_with_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    entries = [AAVE, TRADIFI, STX, "not an object"]

    await _listing(entries).tradable_perpetuals("USDT")

    message = _only(_records(caplog, logging.INFO)).getMessage()
    assert "settlement_currency=USDT" in message
    assert "listed=4" in message
    assert "available=2" in message
    assert "skipped=1" in message
    assert "elapsed_ms=" in message
