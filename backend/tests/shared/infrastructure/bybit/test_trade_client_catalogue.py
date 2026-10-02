"""The ORDER path's read of Bybit's ``linear`` catalogue.

Probe P7 (2026-10-02): Bybit lists 891 ``linear`` entries, a margin of 109
under the 1,000 one page holds. Past it, a market on the second page would be
refused at order time as "not listed" for a perfectly valid signal. These tests
pin that the signed read follows the cursor to the end, and that it still
cannot truncate, loop, or relax how it parses.
"""

from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.execution.application.ports import OpenOrderSpec
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.shared.infrastructure.bybit.catalogue_pages import MAX_PAGES
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import (
    INSTRUMENTS_PATH,
    POSITIONS_PATH,
)
from strategy_manager.shared.infrastructure.bybit.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitTradeClient
from tests.shared.infrastructure.bybit.test_read_client import BTC_PERP

# The venue's bare spelling (``STXUSDT``); TradingView sends ``STXUSDT.P``.
STX_PERP: dict[str, Any] = {**BTC_PERP, "symbol": "STXUSDT", "baseCoin": "STX"}
ETH_PERP: dict[str, Any] = {**BTC_PERP, "symbol": "ETHUSDT", "baseCoin": "ETH"}
CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def _page(entries: list[Any], cursor: str = "") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "retCode": 0,
            "retMsg": "OK",
            "result": {"list": entries, "category": "linear", "nextPageCursor": cursor},
        },
    )


def _client(
    signer: BybitSigner,
    pages: dict[str, httpx.Response] | None,
    recorded: list[httpx.Request],
    *,
    endless: bool = False,
) -> BybitTradeClient:
    """``pages`` is served by the request's ``cursor`` ('' for none). With
    ``endless`` every answer carries a fresh cursor, so the listing never
    ends."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.path == POSITIONS_PATH:
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [{"symbol": "STXUSDT", "leverage": "3"}],
                    },
                },
            )
        assert request.url.path == INSTRUMENTS_PATH
        cursor = request.url.params.get("cursor", "")
        if endless:
            return _page([BTC_PERP], f"c{len(recorded)}")
        assert pages is not None
        return pages[cursor]

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    return BybitTradeClient(http, signer)


def _instrument_requests(recorded: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in recorded if r.url.path == INSTRUMENTS_PATH]


async def test_a_symbol_on_the_second_page_is_found_by_the_per_symbol_lookup(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")},
        recorded,
    )

    rules = await client.perp_rules("STXUSDT")

    assert rules.symbol == "STXUSDT"


async def test_the_adapter_sizes_an_order_for_a_symbol_listed_only_on_page_two(
    signer: BybitSigner,
) -> None:
    """Three spellings across the boundary: TradingView ``STXUSDT.P`` in, the
    venue's ``STXUSDT`` out, found on the listing's second page."""
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")},
        recorded,
    )
    adapter = BybitFuturesExchangeAdapter(client)

    order = await adapter.build_open_order(
        OpenOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol="STXUSDT.P",
            side=OrderSide.BUY,
            granted=Decimal("100"),
            price=Decimal("2"),
        )
    )

    assert order.symbol == "STXUSDT"  # type: ignore[union-attr]
    assert order.base_size == Decimal("150")  # type: ignore[union-attr]


async def test_a_symbol_on_no_page_is_still_refused_as_not_listed(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([ETH_PERP], "")},
        recorded,
    )

    with pytest.raises(BybitApiError, match="does not list 'NOSUCHUSDT'"):
        await client.perp_rules("NOSUCHUSDT")

    assert len(_instrument_requests(recorded)) == 2


async def test_a_one_page_listing_makes_exactly_one_request(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(signer, {"": _page([BTC_PERP, STX_PERP], "")}, recorded)

    await client.perp_rules("STXUSDT")

    requests = _instrument_requests(recorded)
    assert len(requests) == 1
    assert requests[0].url.params["limit"] == "1000"
    assert requests[0].url.params["category"] == "linear"
    assert "cursor" not in requests[0].url.params


async def test_the_empty_string_cursor_ends_the_read(signer: BybitSigner) -> None:
    """The last page's ``nextPageCursor`` is the EMPTY string, not an absent
    field (probe P7). Treating it as a cursor would request page 3 with
    ``cursor=``."""
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")},
        recorded,
    )

    await client.perp_rules("STXUSDT")

    cursors = [r.url.params.get("cursor") for r in _instrument_requests(recorded)]
    assert cursors == [None, "c1"]


async def test_every_request_of_the_loop_is_signed(signer: BybitSigner) -> None:
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")},
        recorded,
    )

    await client.perp_rules("STXUSDT")

    requests = _instrument_requests(recorded)
    assert len(requests) == 2
    for request in requests:
        assert request.headers[KEY_HEADER]
        assert request.headers[SIGNATURE_HEADER]
    # The cursor is part of what is signed, so the two signatures differ.
    assert (
        requests[0].headers[SIGNATURE_HEADER] != requests[1].headers[SIGNATURE_HEADER]
    )


async def test_the_whole_listing_is_read_once_per_client_not_once_per_lookup(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([STX_PERP], "")},
        recorded,
    )

    await client.perp_rules("BTCUSDT")
    await client.perp_rules("STXUSDT")
    await client.perp_rules("stxusdt")

    assert len(_instrument_requests(recorded)) == 2


async def test_a_repeated_cursor_raises_instead_of_looping(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "same"), "same": _page([STX_PERP], "same")},
        recorded,
    )

    with pytest.raises(BybitApiError, match="repeated a page cursor"):
        await client.perp_rules("STXUSDT")

    assert len(_instrument_requests(recorded)) == 2


async def test_the_page_cap_raises_instead_of_returning_a_partial_list(
    signer: BybitSigner,
) -> None:
    recorded: list[httpx.Request] = []
    client = _client(signer, None, recorded, endless=True)

    with pytest.raises(BybitApiError, match=f"{MAX_PAGES} pages"):
        await client.perp_rules("BTCUSDT")

    assert len(_instrument_requests(recorded)) == MAX_PAGES


async def test_a_malformed_entry_on_a_later_page_still_raises(
    signer: BybitSigner,
) -> None:
    """The signed path parses eagerly and refuses one bad entry; reading more
    pages must not relax that into the public catalogue's skip-and-warn."""
    broken = {**STX_PERP, "priceFilter": {"tickSize": 0.1}}
    recorded: list[httpx.Request] = []
    client = _client(
        signer,
        {"": _page([BTC_PERP], "c1"), "c1": _page([broken], "")},
        recorded,
    )

    with pytest.raises(BybitApiError):
        await client.perp_rules("BTCUSDT")


async def test_a_malformed_entry_on_the_first_page_still_raises(
    signer: BybitSigner,
) -> None:
    broken = {**BTC_PERP, "priceFilter": {"tickSize": 0.1}}
    recorded: list[httpx.Request] = []
    client = _client(signer, {"": _page([broken, STX_PERP], "")}, recorded)

    with pytest.raises(BybitApiError):
        await client.perp_rules("STXUSDT")
