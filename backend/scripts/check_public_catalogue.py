"""Probe P7: do the venues' PUBLIC catalogues answer, unsigned, from this host?

This is NOT a test. It talks to the live venues, which is why it lives here and
not under tests/. It is the owner-run gate of PR 12v-0 (decision 41): no line of
the public catalogue adapters is written before its output is recorded in
``openspec/changes/operator-panel/tasks.md`` under "PR 12v-0 -- Probe P7
results".

**It loads no credential, and it cannot sign.** It is GET-only, builds a bare
``httpx.AsyncClient`` and sends no API-key header and no ``signature`` or
``timestamp`` parameter. It imports no signer, no vault and no cipher, and it
builds no order. The only settings it reads are the two base URLs. It prints
counts, symbols and a short allow-list of rate-limit headers: no other header
and no environment value.

Why from the VPS: Binance answers HTTP 451 by location, so "it works from a
laptop" proves nothing about the host the API process runs on.

What it answers, per venue (design addendum section J):

  P7.1  the HTTP status with no signature and no key header
  P7.2  entries listed, by contract type, by status and by settle/margin coin
        (the exact strings the filter compares)
  P7.3  Bybit only: is ``nextPageCursor`` present at ``limit=1000``, is it
        absent or empty on the last page, how many pages does ``limit=200``
        take, and does following the cursor return every entry exactly once
  P7.4  how many pairs survive the filter for USDT
  P7.5  whether SFPUSDT, AAVEUSDT and STXUSDT are available
  P7.6  response bytes, elapsed time and the rate-limit headers

A failure of one venue (HTTP 451, any other HTTP error, a network error, a
Bybit ``retCode`` over HTTP 200) is reported as that venue's outcome and never
hides the other venue's result. The exit code is non-zero if either failed.

**Exact VPS run command** (after this PR is merged and pulled; no restart):

    cd /opt/strategy-manager/app/backend && \\
    sudo -u strategy -H /opt/strategy-manager/.local/bin/uv run python \\
        scripts/check_public_catalogue.py

Usage (from ``backend/``):
    uv run python scripts/check_public_catalogue.py
    uv run python scripts/check_public_catalogue.py --symbol SFPUSDT --symbol ETHUSDT
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from strategy_manager.shared.config import get_settings

KNOWN_PAIRS = ("SFPUSDT", "AAVEUSDT", "STXUSDT")
SETTLEMENT = "USDT"

# The strings the design's filter compares (design addendum section C).
BYBIT_CONTRACT_TYPE = "LinearPerpetual"
BYBIT_STATUS = "Trading"
BINANCE_CONTRACT_TYPE = "PERPETUAL"
BINANCE_STATUS = "TRADING"

BYBIT_PATH = "/v5/market/instruments-info"
BINANCE_PATH = "/fapi/v1/exchangeInfo"
BYBIT_LIMITS = (1000, 200)
# A bound on the cursor loop, so a venue that never ends it cannot hang the probe.
MAX_PAGES = 100
TIMEOUT_SECONDS = 30.0

# The only headers ever printed: those that describe a rate limit.
RATE_LIMIT_PREFIXES = (
    "x-bapi-limit",
    "x-mbx-used-weight",
    "x-mbx-order-count",
    "x-ratelimit",
    "ratelimit",
    "retry-after",
)


@dataclass(frozen=True, slots=True)
class VenueReport:
    """One venue's answers. A failed read must never pass for an empty catalogue."""

    venue: str
    outcome: str = "failed"  # ok | location_refused | http_error | failed
    detail: str = ""
    http_status: int | None = None
    entries: int = 0
    by_contract_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    by_settle_coin: dict[str, int] = field(default_factory=dict)
    cursor_present: bool | None = None  # Bybit: a cursor on the first page at limit=1000
    last_page_cursor: str | None = None  # Bybit: "absent" or "empty" on the last page
    pages_at_1000: int | None = None
    pages_at_200: int | None = None
    every_entry_once: bool | None = None
    usdt_pairs: int = 0
    known_pairs: dict[str, bool] = field(default_factory=dict)
    response_bytes: int = 0
    elapsed_seconds: float = 0.0
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


class VenueFailure(Exception):
    """A venue answered in a way the probe must report rather than count."""

    def __init__(self, outcome: str, detail: str, http_status: int | None = None) -> None:
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail
        self.http_status = http_status


@dataclass(slots=True)
class Pages:
    entries: list[Any] = field(default_factory=list)
    pages: int = 0
    first_page_cursor: bool = False
    last_page_cursor: str = "absent"
    http_status: int = 0
    response_bytes: int = 0
    headers: dict[str, str] = field(default_factory=dict)


def _rate_limit_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name.lower(): value
        for name, value in response.headers.items()
        if name.lower().startswith(RATE_LIMIT_PREFIXES)
    }


async def _get_json(http: httpx.AsyncClient, url: str, params: dict[str, str]) -> httpx.Response:
    response = await http.get(url, params=params)
    status = response.status_code
    if status == 451:
        raise VenueFailure(
            "location_refused", "HTTP 451: the venue refuses requests from this location", status
        )
    if status != 200:
        raise VenueFailure("http_error", f"http={status}", status)
    return response


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise VenueFailure("failed", "the body is not JSON", response.status_code) from exc
    if not isinstance(body, dict):
        raise VenueFailure("failed", "the body is not a JSON object", response.status_code)
    return body


async def _bybit_pages(http: httpx.AsyncClient, base_url: str, limit: int) -> Pages:
    """Reads the whole `linear` listing at `limit`, following `nextPageCursor`."""
    result = Pages()
    cursor = ""
    seen: set[str] = set()
    while True:
        if result.pages >= MAX_PAGES:
            raise VenueFailure("failed", f"the cursor did not end within {MAX_PAGES} pages")
        params = {"category": "linear", "limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        response = await _get_json(http, base_url.rstrip("/") + BYBIT_PATH, params)
        body = _json_object(response)
        if body.get("retCode") != 0:
            raise VenueFailure(
                "failed",
                f"retCode={body.get('retCode')!r} retMsg={body.get('retMsg')!r} over HTTP 200",
                response.status_code,
            )
        payload = body.get("result")
        listing = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(listing, list):
            raise VenueFailure("failed", "result.list is missing or not a list", 200)
        result.pages += 1
        result.http_status = response.status_code
        result.response_bytes += len(response.content)
        if result.pages == 1:
            result.headers = _rate_limit_headers(response)
        result.entries.extend(listing)
        next_cursor = payload.get("nextPageCursor")
        if result.pages == 1:
            result.first_page_cursor = bool(next_cursor)
        if not next_cursor:
            result.last_page_cursor = "absent" if next_cursor is None else "empty"
            return result
        if next_cursor in seen:
            raise VenueFailure("failed", "the cursor repeated: the loop would never end", 200)
        seen.add(next_cursor)
        cursor = next_cursor


def _symbols(entries: Iterable[Any]) -> list[str]:
    return [str(e.get("symbol")) if isinstance(e, dict) else "?" for e in entries]


def _tally(entries: list[Any], key: str) -> dict[str, int]:
    counts = Counter(str(e.get(key) or "?") if isinstance(e, dict) else "?" for e in entries)
    return dict(counts)


def _available(
    entries: list[Any], contract_type: str, status: str, settle_key: str, settle: str
) -> set[str]:
    return {
        str(e["symbol"])
        for e in entries
        if isinstance(e, dict)
        and e.get("contractType") == contract_type
        and e.get("status") == status
        and str(e.get(settle_key) or "").upper() == settle
        and e.get("symbol")
    }


async def _probe_bybit(
    http: httpx.AsyncClient, base_url: str, symbols: tuple[str, ...]
) -> VenueReport:
    started = time.perf_counter()
    big = await _bybit_pages(http, base_url, BYBIT_LIMITS[0])
    small = await _bybit_pages(http, base_url, BYBIT_LIMITS[1])
    elapsed = time.perf_counter() - started

    big_symbols = _symbols(big.entries)
    once = (
        len(set(big_symbols)) == len(big_symbols)
        and len(small.entries) == len(big.entries)
        and set(_symbols(small.entries)) == set(big_symbols)
    )
    available = _available(big.entries, BYBIT_CONTRACT_TYPE, BYBIT_STATUS, "settleCoin", SETTLEMENT)
    return VenueReport(
        venue="bybit",
        outcome="ok",
        http_status=big.http_status,
        entries=len(big.entries),
        by_contract_type=_tally(big.entries, "contractType"),
        by_status=_tally(big.entries, "status"),
        by_settle_coin=_tally(big.entries, "settleCoin"),
        cursor_present=big.first_page_cursor,
        last_page_cursor=big.last_page_cursor,
        pages_at_1000=big.pages,
        pages_at_200=small.pages,
        every_entry_once=once,
        usdt_pairs=len(available),
        known_pairs={s: s in available for s in symbols},
        response_bytes=big.response_bytes,
        elapsed_seconds=elapsed,
        rate_limit_headers=big.headers,
    )


async def _probe_binance(
    http: httpx.AsyncClient, base_url: str, symbols: tuple[str, ...]
) -> VenueReport:
    started = time.perf_counter()
    response = await _get_json(http, base_url.rstrip("/") + BINANCE_PATH, {})
    elapsed = time.perf_counter() - started
    body = _json_object(response)
    listing = body.get("symbols")
    if not isinstance(listing, list):
        raise VenueFailure(
            "failed",
            f"symbols is missing (code={body.get('code')!r} msg={body.get('msg')!r})",
            response.status_code,
        )
    available = _available(
        listing, BINANCE_CONTRACT_TYPE, BINANCE_STATUS, "marginAsset", SETTLEMENT
    )
    return VenueReport(
        venue="binance",
        outcome="ok",
        http_status=response.status_code,
        entries=len(listing),
        by_contract_type=_tally(listing, "contractType"),
        by_status=_tally(listing, "status"),
        by_settle_coin=_tally(listing, "marginAsset"),
        usdt_pairs=len(available),
        known_pairs={s: s in available for s in symbols},
        response_bytes=len(response.content),
        elapsed_seconds=elapsed,
        rate_limit_headers=_rate_limit_headers(response),
    )


async def _guarded(
    venue: str, read: Callable[[], Awaitable[VenueReport]]
) -> VenueReport:
    """Runs one venue without letting its failure hide the other's result."""
    try:
        return await read()
    except VenueFailure as exc:
        return VenueReport(
            venue=venue, outcome=exc.outcome, detail=exc.detail, http_status=exc.http_status
        )
    except Exception as exc:  # noqa: BLE001 - any failure is that venue's result
        return VenueReport(venue=venue, outcome="failed", detail=f"{type(exc).__name__}: {exc}")


async def run(
    *,
    bybit_base_url: str,
    binance_base_url: str,
    symbols: tuple[str, ...] = KNOWN_PAIRS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[VenueReport]:
    """Probes both venues with a bare, unsigned client. Nothing here can sign."""
    async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS) as http:
        bybit = await _guarded("bybit", lambda: _probe_bybit(http, bybit_base_url, symbols))
        binance = await _guarded("binance", lambda: _probe_binance(http, binance_base_url, symbols))
    return [bybit, binance]


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"


def render_report(reports: list[VenueReport]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        lines.append(f"\n=== {report.venue.upper()} ===")
        status = "none" if report.http_status is None else str(report.http_status)
        if report.outcome == "location_refused":
            lines.append(f"  P7.1 LOCATION REFUSED: {report.detail}")
            lines.append("       This is a refusal by location, NOT an empty catalogue.")
            continue
        if report.outcome == "http_error":
            lines.append(f"  P7.1 HTTP ERROR: {report.detail}")
            continue
        if report.outcome != "ok":
            lines.append(f"  P7.1 FAILED (http={status}): {report.detail}")
            continue
        lines.append(f"  P7.1 HTTP {status} with no signature and no key header")
        lines.append(f"  P7.2 entries listed:     {report.entries}")
        lines.append(f"       by contract type:   {_counts(report.by_contract_type)}")
        lines.append(f"       by status:          {_counts(report.by_status)}")
        lines.append(f"       by settle/margin:   {_counts(report.by_settle_coin)}")
        if report.venue == "bybit":
            lines.append(
                f"  P7.3 nextPageCursor at limit=1000: "
                f"{'present' if report.cursor_present else 'absent'}; "
                f"pages={report.pages_at_1000}; last page: {report.last_page_cursor}"
            )
            lines.append(
                f"       pages at limit=200: {report.pages_at_200}; "
                f"every entry exactly once: {'YES' if report.every_entry_once else 'NO'}"
            )
        else:
            lines.append("  P7.3 n/a (Binance has no cursor)")
        lines.append(
            f"  P7.4 pairs surviving the filter for {SETTLEMENT}: {report.usdt_pairs}"
        )
        for symbol, available in report.known_pairs.items():
            lines.append(f"  P7.5 {symbol}: {'available' if available else 'NOT available'}")
        headers = "; ".join(f"{k}: {v}" for k, v in sorted(report.rate_limit_headers.items()))
        lines.append(
            f"  P7.6 {report.response_bytes} bytes; {report.elapsed_seconds:.2f} s; "
            f"rate-limit headers: {headers or 'none'}"
        )
    filter_note = (
        f"\nFilter strings the design relies on: Bybit contractType={BYBIT_CONTRACT_TYPE} "
        f"status={BYBIT_STATUS}; Binance contractType={BINANCE_CONTRACT_TYPE} "
        f"status={BINANCE_STATUS}. Compare them with the counts above."
    )
    lines.append(filter_note)
    return lines


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", dest="symbols")
    args = parser.parse_args()
    symbols = tuple(s.upper() for s in (args.symbols or KNOWN_PAIRS))

    settings = get_settings()
    print(f"Bybit URL:   {settings.bybit_base_url}")
    print(f"Binance URL: {settings.binance_futures_base_url}")
    print(f"Pairs under inspection: {', '.join(symbols)}")
    print("This probe is GET-only and unsigned: no credential is loaded, nothing is placed.")

    reports = await run(
        bybit_base_url=settings.bybit_base_url,
        binance_base_url=settings.binance_futures_base_url,
        symbols=symbols,
    )
    for line in render_report(reports):
        print(line)
    return 0 if all(report.outcome == "ok" for report in reports) else 1


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
