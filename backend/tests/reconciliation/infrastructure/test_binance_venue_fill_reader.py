"""``BinanceVenueFillReader`` and the window fetch it is built on
(``BinanceReadOnlyClient.fills_in_window``) — design decision 9, Blocker c.

Driven through ``httpx.MockTransport`` down to the real client.

**Binding correction to design §9 (found in review):** design said "advance
``startTime`` to the last trade's time + 1ms". That silently drops trades
that share the last trade's millisecond but fell onto the NEXT page. Instead:
on a full page, advance ``startTime`` to the last trade's time INCLUSIVE (no
``+1``), de-duplicate by ``exchange_fill_id``, and if a full page yields ZERO
new ids (every trade in that millisecond exceeds the page size), RAISE —
never loop, never truncate. Live-verified: ``fromId`` cannot be combined with
``startTime``/``endTime`` on this endpoint (HTTP 400, ``-1106``), so
pagination is time-window re-querying, not id-cursor pagination.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from strategy_manager.reconciliation.application.ports import (
    VenueFill,
    VenueFillReadError,
)
from strategy_manager.reconciliation.infrastructure.binance_venue_fill_reader import (
    BinanceVenueFillReader,
)
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
)
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)

POOL = ("binance", "usdt-m", "USDT")
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 9, 2, tzinfo=UTC)

FROZEN_NOW = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return FROZEN_NOW


def _signer() -> BinanceSigner:
    return BinanceSigner(
        BinanceCredentials(api_key="key-abcd", api_secret="test-secret"),
        FrozenClock(),
        recv_window_ms=5000,
    )


def _trade(
    trade_id: int,
    *,
    symbol: str = "STXUSDT_PERP",
    side: str = "BUY",
    qty: str = "10",
    order_id: int | None = 555,
    time_ms: int = 1_789_000_000_000,
) -> dict[str, Any]:
    trade: dict[str, Any] = {
        "id": trade_id,
        "symbol": symbol,
        "side": side,
        "price": "1.5",
        "qty": qty,
        "commission": "0.01",
        "commissionAsset": "USDT",
        "time": time_ms,
    }
    if order_id is not None:
        trade["orderId"] = order_id
    return trade


def _reader(
    handler: Any, *, page_limit: int = 100, max_pages: int = 10
) -> tuple[BinanceVenueFillReader, list[httpx.Request]]:
    recorded: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(wrapped)
    )
    client = BinanceReadOnlyClient(http, _signer())
    reader = BinanceVenueFillReader(client, page_limit=page_limit, max_pages=max_pages)
    return reader, recorded


async def test_a_single_partial_page_ends_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_trade(1), _trade(2)])

    reader, recorded = _reader(handler, page_limit=100)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert [f.exchange_fill_id for f in fills] == ["1", "2"]
    assert all(isinstance(f, VenueFill) for f in fills)
    assert len(recorded) == 1


async def test_full_page_advances_start_time_inclusive_and_dedups() -> None:
    """The corrected rule: advance to the last trade's OWN time (not +1),
    which necessarily re-fetches that same trade on the next page — dedup
    by id removes it, and the trade sharing that millisecond that a naive
    ``+1ms`` would have dropped is kept."""
    # Page 1: 2 trades, both at ms=1000, page_limit=2 -> full page.
    page1 = [_trade(1, time_ms=1000), _trade(2, time_ms=1000)]
    # Page 2 (queried with startTime=1000 inclusive): trade 2 comes back
    # (duplicate, same ms) alongside trade 3, which ALSO shares ms=1000 —
    # exactly the trade a +1ms advance would have silently skipped. Still a
    # full page (2 entries), so one more query re-confirms the boundary.
    page2 = [_trade(2, time_ms=1000), _trade(3, time_ms=1000)]
    # Page 3: only the now-known duplicate comes back, a PARTIAL page — the
    # signal that the window is exhausted.
    page3 = [_trade(3, time_ms=1000)]

    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        pages = {1: page1, 2: page2, 3: page3}
        return httpx.Response(200, json=pages[len(calls)])

    reader, _ = _reader(handler, page_limit=2)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert [f.exchange_fill_id for f in fills] == ["1", "2", "3"]
    # The second call's startTime is the FIRST page's last trade time,
    # unchanged (no +1ms) -- proving the inclusive rule was applied.
    assert calls[1]["startTime"] == "1000"


async def test_full_page_with_zero_new_ids_raises_never_loops() -> None:
    """Every trade in the page shares one millisecond and the page is full:
    advancing (inclusive) brings back the exact same set. That is refused,
    not looped forever and not truncated."""
    page = [_trade(1, time_ms=1000), _trade(2, time_ms=1000)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    reader, recorded = _reader(handler, page_limit=2, max_pages=5)

    with pytest.raises(VenueFillReadError, match="zero new"):
        await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    # Refused on the SECOND page (the first full page, then the repeat that
    # proves it), never retried up to max_pages.
    assert len(recorded) == 2


async def test_max_pages_bound_raises_rather_than_truncating() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Distinct ids and times each call, so it is never the zero-new-ids
        # case -- this proves the SEPARATE max_pages bound.
        call_index = len(recorded)
        recorded.append(request)
        base = call_index * 10
        return httpx.Response(
            200, json=[_trade(base + 1, time_ms=base), _trade(base + 2, time_ms=base)]
        )

    recorded: list[httpx.Request] = []
    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(handler)
    )
    client = BinanceReadOnlyClient(http, _signer())
    reader = BinanceVenueFillReader(client, page_limit=2, max_pages=3)

    with pytest.raises(VenueFillReadError, match="3 pages"):
        await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert len(recorded) == 3


async def test_venue_is_asked_with_the_bare_symbol_never_the_contract_marker() -> None:
    """Spelling rule: the fixture answers ``STXUSDT_PERP``; the reader is
    called with ``STXUSDT.P``."""
    seen_symbols: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_symbols.append(dict(request.url.params)["symbol"])
        return httpx.Response(200, json=[_trade(1, symbol="STXUSDT")])

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert seen_symbols == ["STXUSDT"]
    assert fills[0].symbol == "STXUSDT"


async def test_tolerant_parser_allows_a_missing_order_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_trade(1, order_id=None)])

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert fills[0].exchange_order_id is None


async def test_side_is_normalised_to_buy_sell() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[_trade(1, side="BUY"), _trade(2, side="SELL")]
        )

    reader, _ = _reader(handler)

    fills = await reader.fills_in_window(POOL, "STXUSDT.P", START, END)

    assert {f.exchange_fill_id: f.side for f in fills} == {"1": "BUY", "2": "SELL"}


async def test_an_unrecognised_side_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_trade(1, side="buy")])

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="side"):
        await reader.fills_in_window(POOL, "STXUSDT.P", START, END)


async def test_a_non_positive_quantity_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_trade(1, qty="0")])

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="quantity"):
        await reader.fills_in_window(POOL, "STXUSDT.P", START, END)


async def test_a_venue_refusal_becomes_venue_fill_read_error_with_the_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1106, "msg": "not needed"})

    reader, _ = _reader(handler)

    with pytest.raises(VenueFillReadError, match="not needed"):
        await reader.fills_in_window(POOL, "STXUSDT.P", START, END)


async def test_the_reader_declares_its_own_exchange_and_venues() -> None:
    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    reader = BinanceVenueFillReader(
        BinanceReadOnlyClient(http, _signer()), page_limit=100, max_pages=10
    )

    assert reader.exchange == "binance"
    assert reader.venues == frozenset({"usdt-m"})
