"""``BybitVenueFillReader`` and the window fetch it is built on
(``BybitReadOnlyClient.fills_in_window``) — design decision 9, Blocker c.

Driven through ``httpx.MockTransport`` down to the real client, because the
thing worth proving here is the paging/filtering behaviour against the wire
shape, not a mocked method call.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from strategy_manager.reconciliation.application.ports import (
    VenueFill,
    VenueFillReadError,
)
from strategy_manager.reconciliation.infrastructure.bybit_venue_fill_reader import (
    BybitVenueFillReader,
)
from strategy_manager.shared.infrastructure.bybit.read_client import (
    BybitReadOnlyClient,
)
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    BybitTradeClient,
)

POOL = ("bybit", "usdt-m", "USDT")
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 9, 2, tzinfo=UTC)

FROZEN_NOW = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return FROZEN_NOW


def _signer() -> BybitSigner:
    return BybitSigner(
        BybitCredentials(api_key="key-abcd", api_secret="test-secret"),
        FrozenClock(),
        recv_window_ms=5000,
    )


def _envelope(result: dict[str, Any]) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result, "time": 1787762883000}


def _entry(
    exec_id: str,
    *,
    symbol: str = "STXUSDT",
    side: str = "Buy",
    qty: str = "10",
    order_id: str | None = "order-1",
    exec_type: str = "Trade",
) -> dict[str, Any]:
    entry = {
        "execId": exec_id,
        "symbol": symbol,
        "side": side,
        "execPrice": "1.5",
        "execQty": qty,
        "execFee": "0.01",
        "feeCurrency": "USDT",
        "execTime": "1789000000000",
        "execType": exec_type,
    }
    if order_id is not None:
        entry["orderId"] = order_id
    return entry


def _reader(
    handler: Any, *, page_limit: int = 100, max_pages: int = 10
) -> tuple[BybitVenueFillReader, list[httpx.Request]]:
    recorded: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(wrapped)
    )
    client = BybitReadOnlyClient(http, _signer())
    reader = BybitVenueFillReader(client, page_limit=page_limit, max_pages=max_pages)
    return reader, recorded


async def test_paginates_via_next_page_cursor_until_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        cursor = dict(request.url.params).get("cursor", "")
        if not cursor:
            return httpx.Response(
                200,
                json=_envelope(
                    {"list": [_entry("e1"), _entry("e2")], "nextPageCursor": "page-2"}
                ),
            )
        assert cursor == "page-2"
        return httpx.Response(
            200, json=_envelope({"list": [_entry("e3")], "nextPageCursor": ""})
        )

    reader, recorded = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT", START, END)

    assert [f.exchange_fill_id for f in fills] == ["e1", "e2", "e3"]
    assert all(isinstance(f, VenueFill) for f in fills)
    assert len(recorded) == 2


async def test_max_pages_bound_raises_rather_than_truncating() -> None:
    """A page always full, cursor never empty: never loop forever, never
    silently stop with a partial list."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {"list": [_entry("dup", qty="1")], "nextPageCursor": "still-more"}
            ),
        )

    reader, recorded = _reader(handler, max_pages=3)

    with pytest.raises(VenueFillReadError, match="3 pages"):
        await reader.fills_in_window(POOL, "STXUSDT", START, END)

    assert len(recorded) == 3


async def test_tolerant_parser_allows_a_missing_order_id() -> None:
    """The window fetch's own parser is tolerant; the strict order-scoped
    ``_parse_execution`` in ``trade_client.py`` stays untouched and still
    requires one."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {"list": [_entry("liq-1", order_id=None)], "nextPageCursor": ""}
            ),
        )

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT", START, END)

    assert fills[0].exchange_order_id is None

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=_envelope(
                    {"list": [_entry("liq-1", order_id=None)]}
                ),
            )
        ),
    )
    trade_client = BybitTradeClient(http, _signer())
    with pytest.raises(Exception, match="orderId"):
        await trade_client.fills_for("some-order-link-id")


async def test_venue_is_asked_with_the_bare_symbol_never_the_contract_marker() -> None:
    """Spelling rule: the fixture answers ``STXUSDT``; the reader is called
    with ``STXUSDT.P``."""
    seen_symbols: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_symbols.append(dict(request.url.params)["symbol"])
        return httpx.Response(
            200, json=_envelope({"list": [_entry("e1", symbol="STXUSDT")], "nextPageCursor": ""})
        )

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert seen_symbols == ["STXUSDT"]
    assert fills[0].symbol == "STXUSDT"


async def test_funding_exec_type_is_excluded_bust_and_adl_are_kept() -> None:
    """A funding charge is not a position change and must never be booked
    as a close; BustTrade and AdlTrade are still trade-type executions."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {
                    "list": [
                        _entry("funding-1", exec_type="Funding"),
                        _entry("bust-1", exec_type="BustTrade"),
                        _entry("adl-1", exec_type="AdlTrade"),
                    ],
                    "nextPageCursor": "",
                }
            ),
        )

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT", START, END)

    assert {f.exchange_fill_id for f in fills} == {"bust-1", "adl-1"}


async def test_an_unrecognised_exec_type_raises_naming_it() -> None:
    """Neither a known trade type nor ``Funding`` — never silently skipped,
    never silently included."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {"list": [_entry("delivery-1", exec_type="Delivery")], "nextPageCursor": ""}
            ),
        )

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="Delivery"):
        await reader.fills_in_window(POOL, "STXUSDT", START, END)


async def test_side_is_normalised_to_buy_sell() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                {
                    "list": [_entry("e1", side="Buy"), _entry("e2", side="Sell")],
                    "nextPageCursor": "",
                }
            ),
        )

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT", START, END)

    by_id = {f.exchange_fill_id: f.side for f in fills}
    assert by_id == {"e1": "BUY", "e2": "SELL"}


async def test_an_unrecognised_side_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope({"list": [_entry("e1", side="None")], "nextPageCursor": ""})
        )

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="side"):
        await reader.fills_in_window(POOL, "STXUSDT", START, END)


async def test_a_non_positive_quantity_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_envelope({"list": [_entry("e1", qty="0")], "nextPageCursor": ""})
        )

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="quantity"):
        await reader.fills_in_window(POOL, "STXUSDT", START, END)


async def test_a_venue_refusal_becomes_venue_fill_read_error_with_the_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"retCode": 10006, "retMsg": "rate limited", "result": {}, "time": 0},
        )

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="rate limited"):
        await reader.fills_in_window(POOL, "STXUSDT", START, END)


async def test_the_reader_declares_its_own_exchange_and_venues() -> None:
    http = httpx.AsyncClient(
        base_url="https://api.bybit.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_envelope({}))),
    )
    reader = BybitVenueFillReader(
        BybitReadOnlyClient(http, _signer()), page_limit=100, max_pages=10
    )

    assert reader.exchange == "bybit"
    assert reader.venues == frozenset({"usdt-m"})
