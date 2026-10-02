"""The credential-free Bybit catalogue: which linear perpetuals a pool may use.

Venue spelling only: every symbol here is Bybit's own (``STXUSDT``). The
``market_key`` mapping happens one layer up, where the pool is known.
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.public_catalogue import (
    MAX_PAGES,
    BybitPublicCatalogue,
)
from strategy_manager.shared.infrastructure.bybit.transport import (
    BybitPublicTransport,
)
from tests.shared.infrastructure.bybit.test_read_client import BTC_DATED, BTC_PERP

LOGGER = "strategy_manager.shared.infrastructure.bybit.public_catalogue"

STX_PERP: dict[str, Any] = {**BTC_PERP, "symbol": "STXUSDT", "baseCoin": "STX"}
USDC_PERP: dict[str, Any] = {
    **BTC_PERP,
    "symbol": "BTCPERP",
    "settleCoin": "USDC",
    "quoteCoin": "USDC",
}
HALTED_PERP: dict[str, Any] = {**BTC_PERP, "symbol": "HALTUSDT", "status": "Closed"}

ABSENT = object()


def _page(entries: list[Any], cursor: Any = "") -> dict[str, Any]:
    """One answer. ``cursor=ABSENT`` leaves the key out altogether."""
    result: dict[str, Any] = {"list": entries, "category": "linear"}
    if cursor is not ABSENT:
        result["nextPageCursor"] = cursor
    return {"retCode": 0, "retMsg": "OK", "result": result}


def _catalogue(
    answer: Callable[[httpx.Request], httpx.Response],
    recorded: list[httpx.Request] | None = None,
) -> BybitPublicCatalogue:
    def handler(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.append(request)
        return answer(request)

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    return BybitPublicCatalogue(BybitPublicTransport(http))


def _single(entries: list[Any]) -> BybitPublicCatalogue:
    return _catalogue(lambda _: httpx.Response(200, json=_page(entries)))


def _paged(pages: dict[str, dict[str, Any]], recorded: list[httpx.Request]) -> BybitPublicCatalogue:
    """Serves ``pages`` by the request's ``cursor`` parameter ('' for none)."""
    return _catalogue(
        lambda request: httpx.Response(
            200, json=pages[request.url.params.get("cursor", "")]
        ),
        recorded,
    )


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == level]


def _only(records: list[logging.LogRecord]) -> logging.LogRecord:
    """The one record expected, asserted rather than unpacked so a missing or a
    duplicated line fails on an assertion that names the count."""
    assert len(records) == 1, [r.getMessage() for r in records]
    return records[0]


# --- the filter -------------------------------------------------------------


async def test_tradable_perpetuals_keeps_trading_perpetuals_settled_in_the_asked_currency_only() -> None:  # noqa: E501
    catalogue = _single([BTC_PERP, BTC_DATED, USDC_PERP, HALTED_PERP, STX_PERP])

    usdt = await catalogue.tradable_perpetuals("USDT")
    usdc = await catalogue.tradable_perpetuals("USDC")

    assert usdt == ("BTCUSDT", "STXUSDT")
    assert usdc == ("BTCPERP",)


async def test_a_dated_future_is_excluded_by_its_contract_type_not_by_its_symbol() -> None:
    """The symbol text is never the criterion, in either direction: a dated
    future with a plain symbol is out, and a perpetual whose symbol LOOKS dated
    is in."""
    dated_plain = {**BTC_DATED, "symbol": "ETHUSDT"}
    perp_dated_looking = {**BTC_PERP, "symbol": "BTCUSDT-25DEC26"}

    kept = await _single([dated_plain, perp_dated_looking]).tradable_perpetuals("USDT")

    assert kept == ("BTCUSDT-25DEC26",)


# --- pagination -------------------------------------------------------------


async def test_the_cursor_is_followed_until_empty_and_every_page_is_read() -> None:
    recorded: list[httpx.Request] = []
    pages = {
        "": _page([BTC_PERP], "c1"),
        "c1": _page([STX_PERP], "c2"),
        "c2": _page([{**BTC_PERP, "symbol": "ETHUSDT"}], ""),
    }

    symbols = await _paged(pages, recorded).tradable_perpetuals("USDT")

    assert symbols == ("BTCUSDT", "STXUSDT", "ETHUSDT")
    assert [r.url.params.get("cursor") for r in recorded] == [None, "c1", "c2"]


async def test_an_absent_cursor_key_ends_the_read_like_an_empty_one() -> None:
    recorded: list[httpx.Request] = []
    pages = {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], ABSENT)}

    symbols = await _paged(pages, recorded).tradable_perpetuals("USDT")

    assert symbols == ("BTCUSDT", "STXUSDT")
    assert len(recorded) == 2


async def test_the_page_cap_raises_instead_of_returning_a_partial_list() -> None:
    recorded: list[httpx.Request] = []
    catalogue = _catalogue(
        lambda _: httpx.Response(200, json=_page([BTC_PERP], "never-ends")), recorded
    )

    with pytest.raises(BybitApiError, match=f"{MAX_PAGES} pages"):
        await catalogue.tradable_perpetuals("USDT")

    assert len(recorded) == MAX_PAGES


# --- malformed entries ------------------------------------------------------


async def test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    broken_amount = {**BTC_PERP, "symbol": "BADUSDT", "priceFilter": {"tickSize": 0.1}}
    no_symbol = {key: value for key, value in BTC_PERP.items() if key != "symbol"}
    entries = [BTC_PERP, broken_amount, "not an object", no_symbol, STX_PERP]

    symbols = await _single(entries).tradable_perpetuals("USDT")

    assert symbols == ("BTCUSDT", "STXUSDT")
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
    broken = [
        {**BTC_PERP, "symbol": f"BAD{index:02d}USDT", "priceFilter": "nope"}
        for index in range(12)
    ]

    await _single([BTC_PERP, *broken]).tradable_perpetuals("USDT")

    warning = _only(_records(caplog, logging.WARNING))
    message = warning.getMessage()
    assert "12" in message
    assert "BAD09USDT" in message
    assert "BAD10USDT" not in message


async def test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error_naming_the_types_seen(  # noqa: E501
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The Pionex lesson: a renamed value turns every valid symbol into an
    "unknown pair", which is a wrong message rather than a refusal."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    renamed = {**BTC_PERP, "contractType": "LinearPerpetualV2", "status": "Live"}

    with pytest.raises(BybitApiError, match="no tradable perpetual"):
        await _single([renamed, BTC_DATED]).tradable_perpetuals("USDT")

    error = _only(_records(caplog, logging.ERROR))
    message = error.getMessage()
    assert "LinearPerpetualV2" in message
    assert "LinearFutures" in message
    assert "Live" in message


async def test_an_empty_listing_is_not_mistaken_for_an_unreadable_one() -> None:
    assert await _single([]).tradable_perpetuals("USDT") == ()


# --- what an operator sees --------------------------------------------------


async def test_a_real_read_logs_one_info_with_counts_and_pages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    pages = {
        "": _page([BTC_PERP, BTC_DATED], "c1"),
        "c1": _page([STX_PERP, "not an object"], ""),
    }

    await _paged(pages, []).tradable_perpetuals("USDT")

    info = _only(_records(caplog, logging.INFO))
    message = info.getMessage()
    assert "settlement_currency=USDT" in message
    assert "listed=4" in message
    assert "available=2" in message
    assert "skipped=1" in message
    assert "pages=2" in message
    assert "elapsed_ms=" in message


async def test_every_request_goes_to_the_instruments_path_with_category_linear_and_no_auth() -> (
    None
):
    recorded: list[httpx.Request] = []
    pages = {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")}

    await _paged(pages, recorded).tradable_perpetuals("USDT")

    assert len(recorded) == 2
    for request in recorded:
        assert request.method == "GET"
        assert request.url.host == "api.bybit.com"
        assert request.url.path == "/v5/market/instruments-info"
        assert request.url.params["category"] == "linear"
        assert request.url.params["limit"] == "1000"
        assert [n for n in request.headers if n.lower().startswith("x-bapi")] == []
        assert "signature" not in request.url.params
        assert "timestamp" not in request.url.params
