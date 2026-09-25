"""Live probe: what the fill-window endpoints will actually answer, on both
venues, before any interval or window constant is fixed (design decision 10).

GET-only. Places nothing, changes no setting. Answers, per venue:

  (a) max accepted window span, bisected across 1d/7d/8d/30d/90d;
  (b) pagination shape and page size; whether an empty window is `[]` or an
      error; on Binance, whether `fromId` and `startTime`/`endTime` combine;
  (c) rate-limit weight per call, as the DIFFERENCE between two responses'
      limit headers;
  (d) whether a LIQUIDATION fill appears on the fill endpoint and carries an
      order id -- inspected from existing history only, never inferred;
  (e) venue server time vs this host's clock (sets `pad`);
  (f) whether the configured key is ACCEPTED on the fill endpoint at all.

Every item prints one of three verdicts -- ANSWERED, REFUSED (with the
venue's own code), or UNKNOWN -- and the three are never conflated: an
unreachable call or an empty history is UNKNOWN, not a guessed "no".

Both venues sign with their VAULT credential (design decision 18, ONE key per
exchange -- superseding decision 9's earlier Bybit-vault/Binance-`.env`
split). Which key is running is printed before any call, via
`probe_credentials.announce` (CLAUDE.md's two-keys lesson).

Usage (from `backend/`):
    uv run python scripts/check_venue_fill_windows.py
    uv run python scripts/check_venue_fill_windows.py --symbol ETHUSDT --lookback-days 30

**Run on the worker's host** -- Binance weight is counted per IP, so a
measurement from anywhere else is not about production (same rule
`measure_reconciliation_rate_limits.py` follows).

**Exact VPS run command** (production runs `main` at 2399510 and will not
check out this branch; this extracts one file from the feature branch and
runs it against the deployed package):

    cd /opt/strategy-manager/app/backend && \\
    sudo -u strategy -H git fetch origin && \\
    sudo -u strategy -H git show \\
        origin/feat/book-venue-closes:backend/scripts/check_venue_fill_windows.py \\
        > /tmp/check_venue_fill_windows.py && \\
    sudo -u strategy -H /opt/strategy-manager/.local/bin/uv run python \\
        /tmp/check_venue_fill_windows.py

**Why this file is self-sufficient about `probe_credentials`.** The VPS
command above extracts ONLY this one file to `/tmp` -- `probe_credentials.py`
is not copied alongside it, so `__file__`'s own directory (`/tmp`) does not
have it. `probe_credentials.py` does still exist, unchanged, at
`backend/scripts/probe_credentials.py` on the deployed `main`, and the VPS
command `cd`s into `backend/` before running anything -- so the current
working directory, not `__file__`, is the path that is still correct
regardless of where this file itself was copied to. The bootstrap below tries
`__file__`'s own directory first (so the ordinary `cd backend && uv run
python scripts/check_venue_fill_windows.py` invocation needs no path
surgery at all) and falls back to `<cwd>/scripts` only when that fails.
"""

import argparse
import asyncio
import io
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx

_SCRIPTS_DIR_CANDIDATES = (Path(__file__).resolve().parent, Path.cwd() / "scripts")
for _candidate in _SCRIPTS_DIR_CANDIDATES:
    if (_candidate / "probe_credentials.py").is_file():
        _candidate_str = str(_candidate)
        if _candidate_str not in sys.path:
            sys.path.insert(0, _candidate_str)
        break
else:
    raise SystemExit(
        "Cannot find probe_credentials.py next to this file or under "
        "<cwd>/scripts. Run this from `backend/` (see the module docstring "
        "for the exact VPS command) so the working directory carries it."
    )

from probe_credentials import announce, vault_credentials  # noqa: E402

from strategy_manager.shared.config import get_settings  # noqa: E402
from strategy_manager.shared.infrastructure.alert_redaction import redact  # noqa: E402
from strategy_manager.shared.infrastructure.binance import (  # noqa: E402
    EXCHANGE as BINANCE_EXCHANGE,
)
from strategy_manager.shared.infrastructure.binance.signer import (  # noqa: E402
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.bybit import EXCHANGE as BYBIT_EXCHANGE  # noqa: E402
from strategy_manager.shared.infrastructure.bybit.signer import (  # noqa: E402
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.clock import SystemClock  # noqa: E402

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_PAGE_LIMIT = 50
SPAN_CANDIDATES_DAYS: tuple[int, ...] = (1, 7, 8, 30, 90)
DAY_MS = 24 * 60 * 60 * 1000

BYBIT_FILLS_PATH = "/v5/execution/list"
BYBIT_SERVER_TIME_PATH = "/v5/market/time"
BYBIT_LIMIT_STATUS_HEADER = "x-bapi-limit-status"
LINEAR = "linear"
# Bybit V5 execType enum (Trade, Funding, AdlTrade, BustTrade, Delivery,
# BlockTrade, MovePosition). A forced liquidation lands as BustTrade; ADL
# (auto-deleverage against this position) is the venue-side twin of one, so
# both count as "a liquidation fill" for item (d).
BYBIT_LIQUIDATION_EXEC_TYPES = frozenset({"BustTrade", "AdlTrade"})

BINANCE_FILLS_PATH = "/fapi/v1/userTrades"
BINANCE_FORCE_ORDERS_PATH = "/fapi/v1/forceOrders"
BINANCE_SERVER_TIME_PATH = "/fapi/v1/time"
BINANCE_USED_WEIGHT_1M_HEADER = "x-mbx-used-weight-1m"

ITEM_LABELS = {
    "a": "(a) max accepted window span",
    "b": "(b) pagination shape",
    "c": "(c) rate-limit weight per call",
    "d": "(d) liquidation fill + order id",
    "e": "(e) server clock skew",
    "f": "(f) key accepted on fill endpoint",
}
ITEM_ORDER = ("f", "e", "a", "b", "c", "d")


ItemStatus = Literal["answered", "refused", "unknown"]
SpanVerdict = Literal["accepted", "refused", "unknown"]


@dataclass(frozen=True, slots=True)
class ItemVerdict:
    """One of the six items' answer. ``code`` is the venue's own refusal
    code, never a guess, and is ``None`` outside the ``refused`` status."""

    status: ItemStatus
    detail: str
    code: str | None = None


@dataclass(frozen=True, slots=True)
class SpanProbe:
    """One bisection call's outcome, kept as evidence rather than folded
    into a single number."""

    days: int
    verdict: SpanVerdict
    detail: str


@dataclass(frozen=True, slots=True)
class SpanBisectionResult:
    probes: tuple[SpanProbe, ...]
    max_accepted_days: int | None
    first_refused: SpanProbe | None


@dataclass(frozen=True, slots=True)
class Args:
    symbol: str
    lookback_days: int
    span_candidates_days: tuple[int, ...]
    page_limit: int


# --- pure helpers (RED-tested; no venue I/O) --------------------------------


def format_item_verdict(item: str, verdict: ItemVerdict) -> str:
    """Renders one item's verdict, distinguishing ANSWERED, REFUSED (with the
    venue's own code) and UNKNOWN -- the three-way distinction the brief
    requires, never collapsed into a bare yes/no."""
    label = ITEM_LABELS.get(item, item)
    if verdict.status == "refused":
        return f"{label}: REFUSED ({verdict.code}) -- {verdict.detail}"
    if verdict.status == "unknown":
        return f"{label}: UNKNOWN -- {verdict.detail}"
    return f"{label}: ANSWERED -- {verdict.detail}"


def header_call_cost(
    before: Mapping[str, str],
    after: Mapping[str, str],
    header_name: str,
    direction: Literal["increasing", "decreasing"],
) -> int | None:
    """The cost of one call, read as the change in a running-counter header
    between two responses to the SAME endpoint.

    ``direction`` names which way the venue's own counter moves as budget is
    spent: Binance's used-weight header COUNTS UP, Bybit's remaining-status
    header COUNTS DOWN. It is a parameter rather than an assumption, because
    reading the wrong direction is exactly how a rolled-over window would
    silently report a cost of zero instead of an honest ``None``.

    Returns ``None`` when the header is absent from either response, is not
    an integer, or moved the WRONG way for the given direction -- a rollover
    invalidates the pair rather than reporting a stale cost, matching the
    guard `measure_reconciliation_rate_limits.py` already uses for Binance.
    """
    key = header_name.lower()
    lowered_before = {name.lower(): value for name, value in before.items()}
    lowered_after = {name.lower(): value for name, value in after.items()}
    if key not in lowered_before or key not in lowered_after:
        return None
    try:
        first = int(lowered_before[key])
        second = int(lowered_after[key])
    except ValueError:
        return None
    cost = second - first if direction == "increasing" else first - second
    # Every call costs at least one unit, so zero means the window reset
    # between the two readings: unmeasured, never "free".
    return cost if cost > 0 else None


def clock_skew_ms(server_ms: int, sent_ms: int, received_ms: int) -> tuple[int, int]:
    """``(server - host, round_trip)`` in ms, the host side taken at the
    MIDPOINT of the request. The server stamped its time somewhere inside the
    round trip, so the skew is only known to within half of it -- which is why
    the round trip is returned alongside rather than dropped."""
    midpoint_ms = (sent_ms + received_ms) // 2
    return server_ms - midpoint_ms, received_ms - sent_ms


async def bisect_max_accepted_span(
    candidates: Sequence[int], probe: Callable[[int], Awaitable[SpanProbe]]
) -> SpanBisectionResult:
    """Binary search across a SORTED set of candidate day-spans for the
    boundary between accepted and refused, calling ``probe`` only at the
    positions the search actually needs -- not at every candidate.

    Assumes the venue is monotonic (smaller spans accepted, larger ones
    refused past some point), which is the assumption design decision 10
    itself makes by calling this a bisection rather than a linear scan. If
    the venue is NOT monotonic, this still terminates and reports every call
    it made in ``probes`` -- it just may not find the true boundary, which
    stays visible in the trace rather than hidden behind a wrong number.

    An ``"unknown"`` result (a raised exception, a malformed body) narrows
    the search the same DIRECTION as ``"refused"`` -- it is not evidence a
    larger span would work -- but is never reported as ``first_refused``:
    an inconclusive call is not a refusal, and conflating the two would put
    a fabricated error code in front of a config default.
    """
    ordered = sorted(set(candidates))
    if not ordered:
        raise ValueError("candidates must not be empty")
    performed: list[SpanProbe] = []
    lo, hi = 0, len(ordered) - 1
    max_accepted_index = -1
    first_refused: SpanProbe | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        result = await probe(ordered[mid])
        performed.append(result)
        if result.verdict == "accepted":
            max_accepted_index = max(max_accepted_index, mid)
            lo = mid + 1
        else:
            if result.verdict == "refused" and (
                first_refused is None or ordered[mid] < first_refused.days
            ):
                first_refused = result
            hi = mid - 1
    max_accepted_days = ordered[max_accepted_index] if max_accepted_index >= 0 else None
    return SpanBisectionResult(
        probes=tuple(performed),
        max_accepted_days=max_accepted_days,
        first_refused=first_refused,
    )


def parse_args(argv: Sequence[str] | None = None) -> Args:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYMBOL,
        help="the bare venue spelling, sent to both venues unchanged "
        f"(default: {DEFAULT_SYMBOL})",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="how far back item (d)'s liquidation history scan and the "
        f"acceptance/pagination probes look (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--span-days",
        type=int,
        nargs="+",
        default=list(SPAN_CANDIDATES_DAYS),
        help="candidate window spans, in days, that item (a) bisects across "
        f"(default: {list(SPAN_CANDIDATES_DAYS)})",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help=f"page size requested for item (b)/(c)/(d) calls (default: {DEFAULT_PAGE_LIMIT})",
    )
    parsed = parser.parse_args(argv)
    if parsed.lookback_days <= 0:
        raise ValueError("--lookback-days must be positive")
    if parsed.page_limit <= 0:
        raise ValueError("--page-limit must be positive")
    if any(days <= 0 for days in parsed.span_days):
        raise ValueError("--span-days must all be positive")
    return Args(
        symbol=str(parsed.symbol).upper(),
        lookback_days=parsed.lookback_days,
        span_candidates_days=tuple(sorted(set(parsed.span_days))),
        page_limit=parsed.page_limit,
    )


# --- shared, venue-agnostic plumbing ----------------------------------------


def _epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def describe_failure(exc: BaseException) -> str:
    """An exception as one printable line, with every known secret shape
    removed. The owner pastes this script's output into a chat, and a
    transport error that echoes its request URL would carry Binance's
    query-string signature along with it."""
    return redact(f"{type(exc).__name__}: {exc}")


async def _safe_item(coro: Awaitable[ItemVerdict], label: str) -> ItemVerdict:
    """One item's own guard: a transient failure (timeout, connection reset)
    becomes THAT item's UNKNOWN verdict, never a lost venue -- the other five
    items' already-obtained answers must survive it."""
    try:
        return await coro
    except Exception as exc:  # deliberately broad, and only here -- see docstring
        return ItemVerdict("unknown", f"{describe_failure(exc)} (answering item {label})")


def _span_result_to_verdict(result: SpanBisectionResult) -> ItemVerdict:
    trace = ", ".join(f"{probe.days}d={probe.verdict}" for probe in result.probes)
    if result.first_refused is not None:
        return ItemVerdict(
            "answered",
            f"max accepted {result.max_accepted_days}d, first refusal at "
            f"{result.first_refused.days}d ({result.first_refused.detail}); trace: {trace}",
        )
    if result.max_accepted_days is not None:
        return ItemVerdict(
            "answered",
            f"every probed candidate was accepted (max probed "
            f"{result.max_accepted_days}d), no refusal observed; trace: {trace}",
        )
    return ItemVerdict("unknown", f"no span produced a clear accept/refuse answer; trace: {trace}")


def _headers_map(response: httpx.Response) -> dict[str, str]:
    return {name.decode("latin-1"): value.decode("latin-1") for name, value in response.headers.raw}


# --- Bybit -------------------------------------------------------------------


async def _bybit_signed_get(
    http: httpx.AsyncClient, signer: BybitSigner, path: str, params: Mapping[str, str]
) -> httpx.Response:
    signed = signer.sign_get(path, params)
    return await http.get(signed.path_with_query, headers=dict(signed.headers))


def _bybit_envelope(response: httpx.Response) -> tuple[int | None, str, Mapping[str, Any]]:
    """(retCode, retMsg, result) -- Bybit answers a rejection with HTTP 200
    and a non-zero retCode, so the status line alone would read a refusal as
    an answer (same trap `measure_reconciliation_rate_limits.py` names)."""
    try:
        body: Any = response.json()
    except ValueError:
        return None, "non-JSON body", {}
    if not isinstance(body, dict):
        return None, "non-object body", {}
    code = body.get("retCode")
    result = body.get("result")
    return (
        code if isinstance(code, int) else None,
        str(body.get("retMsg", "")),
        result if isinstance(result, dict) else {},
    )


async def _bybit_clock_skew(http: httpx.AsyncClient) -> ItemVerdict:
    # Warm the connection first: the TLS handshake would otherwise sit
    # inside the measured round trip and widen its uncertainty.
    await http.get(BYBIT_SERVER_TIME_PATH)
    sent_ms = _epoch_ms(SystemClock().now())
    response = await http.get(BYBIT_SERVER_TIME_PATH)
    received_ms = _epoch_ms(SystemClock().now())
    try:
        body: Any = response.json()
    except ValueError:
        return ItemVerdict("unknown", f"HTTP {response.status_code}, non-JSON body")
    result = body.get("result") if isinstance(body, dict) else None
    time_nano = result.get("timeNano") if isinstance(result, dict) else None
    if time_nano is None:
        keys = sorted(body) if isinstance(body, dict) else "?"
        return ItemVerdict("unknown", f"no result.timeNano in body; keys={keys}")
    try:
        server_ms = int(time_nano) // 1_000_000
    except (TypeError, ValueError):
        return ItemVerdict("unknown", f"timeNano not an integer: {time_nano!r}")
    skew_ms, round_trip_ms = clock_skew_ms(server_ms, sent_ms, received_ms)
    return ItemVerdict(
        "answered",
        f"server - host = {skew_ms} ms +/- {round_trip_ms // 2} ms "
        f"(positive: venue ahead; round trip {round_trip_ms} ms)",
    )


async def _bybit_key_acceptance(
    http: httpx.AsyncClient, signer: BybitSigner, symbol: str, start_ms: int, end_ms: int
) -> ItemVerdict:
    response = await _bybit_signed_get(
        http,
        signer,
        BYBIT_FILLS_PATH,
        {
            "category": LINEAR,
            "symbol": symbol,
            "limit": "1",
            "startTime": str(start_ms),
            "endTime": str(end_ms),
        },
    )
    if response.status_code != 200:
        return ItemVerdict(
            "refused",
            f"HTTP {response.status_code}: {response.text[:200]}",
            code=str(response.status_code),
        )
    code, msg, _ = _bybit_envelope(response)
    if code is None:
        return ItemVerdict("unknown", "non-JSON or non-object body")
    if code == 0:
        return ItemVerdict("answered", "retCode=0 -- this key is accepted on the fill endpoint")
    return ItemVerdict("refused", f"retMsg={msg!r}", code=str(code))


async def _bybit_pagination(
    http: httpx.AsyncClient,
    signer: BybitSigner,
    symbol: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
) -> ItemVerdict:
    response = await _bybit_signed_get(
        http,
        signer,
        BYBIT_FILLS_PATH,
        {
            "category": LINEAR,
            "symbol": symbol,
            "limit": str(page_limit),
            "startTime": str(start_ms),
            "endTime": str(end_ms),
        },
    )
    code, msg, result = _bybit_envelope(response)
    if code != 0:
        status: ItemStatus = "unknown" if code is None else "refused"
        return ItemVerdict(
            status, f"retCode={code} retMsg={msg!r}", code=None if code is None else str(code)
        )
    entries = result.get("list")
    cursor = result.get("nextPageCursor")
    if not isinstance(entries, list):
        return ItemVerdict("unknown", f"result.list missing or not a list; keys={sorted(result)}")
    detail = (
        f"{len(entries)} entries (limit={page_limit}), "
        f"nextPageCursor={cursor!r} ('' means no further page)"
    )

    empty_response = await _bybit_signed_get(
        http,
        signer,
        BYBIT_FILLS_PATH,
        {
            "category": LINEAR,
            "symbol": symbol,
            "limit": str(page_limit),
            "startTime": str(end_ms - 1000),
            "endTime": str(end_ms),
        },
    )
    empty_code, _, empty_result = _bybit_envelope(empty_response)
    detail += f"; a 1s window returned retCode={empty_code} list={empty_result.get('list')!r}"
    return ItemVerdict("answered", detail)


async def _bybit_weight_cost(
    http: httpx.AsyncClient, signer: BybitSigner, symbol: str, start_ms: int, end_ms: int
) -> ItemVerdict:
    params = {
        "category": LINEAR,
        "symbol": symbol,
        "limit": "1",
        "startTime": str(start_ms),
        "endTime": str(end_ms),
    }
    first = await _bybit_signed_get(http, signer, BYBIT_FILLS_PATH, params)
    second = await _bybit_signed_get(http, signer, BYBIT_FILLS_PATH, params)
    cost = header_call_cost(
        _headers_map(first), _headers_map(second), BYBIT_LIMIT_STATUS_HEADER, "decreasing"
    )
    if cost is None:
        return ItemVerdict(
            "unknown",
            f"{BYBIT_LIMIT_STATUS_HEADER} missing, unchanged (window reset between calls) "
            "or moved the wrong way",
        )
    return ItemVerdict(
        "answered", f"{cost} unit(s) of {BYBIT_LIMIT_STATUS_HEADER} per call to {BYBIT_FILLS_PATH}"
    )


async def _bybit_liquidation_check(
    http: httpx.AsyncClient,
    signer: BybitSigner,
    symbol: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
) -> ItemVerdict:
    response = await _bybit_signed_get(
        http,
        signer,
        BYBIT_FILLS_PATH,
        {
            "category": LINEAR,
            "symbol": symbol,
            "limit": str(page_limit),
            "startTime": str(start_ms),
            "endTime": str(end_ms),
        },
    )
    code, msg, result = _bybit_envelope(response)
    if code != 0:
        status: ItemStatus = "unknown" if code is None else "refused"
        return ItemVerdict(
            status, f"retCode={code} retMsg={msg!r}", code=None if code is None else str(code)
        )
    entries = result.get("list")
    if not isinstance(entries, list):
        return ItemVerdict("unknown", f"result.list missing; keys={sorted(result)}")
    exec_types: set[str] = {
        str(entry.get("execType")) for entry in entries if isinstance(entry, dict)
    }
    markers = exec_types & BYBIT_LIQUIDATION_EXEC_TYPES
    if not markers:
        return ItemVerdict(
            "unknown", f"no liquidation in history -- execTypes seen: {sorted(exec_types)}"
        )
    carrying_order_id = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("execType") in markers and entry.get("orderId")
    ]
    return ItemVerdict(
        "answered",
        f"{sorted(markers)} present in {len(entries)} fills; "
        f"{len(carrying_order_id)} of them carry a non-empty orderId",
    )


async def check_bybit(
    http: httpx.AsyncClient,
    signer: BybitSigner,
    symbol: str,
    now: datetime,
    span_candidates_days: Sequence[int],
    lookback_days: int,
    page_limit: int,
) -> dict[str, ItemVerdict]:
    """Runs all six items against Bybit. (e) is unsigned and always
    attempted; (f) gates (a)-(d), which are all signed -- if the key is not
    accepted, further signed calls would fail for the SAME reason and
    reporting them as span/pagination/weight/liquidation refusals would
    misattribute an auth failure to a window-shape limit."""
    results: dict[str, ItemVerdict] = {}
    end_ms = _epoch_ms(now)
    start_ms = end_ms - lookback_days * DAY_MS

    results["e"] = await _safe_item(_bybit_clock_skew(http), "e")
    results["f"] = await _safe_item(
        _bybit_key_acceptance(http, signer, symbol, start_ms, end_ms), "f"
    )
    if results["f"].status != "answered":
        blocked = ItemVerdict("unknown", "key not accepted on this endpoint -- see item (f)")
        results["a"] = results["b"] = results["c"] = results["d"] = blocked
        return results

    async def probe_span(days: int) -> SpanProbe:
        span_start = end_ms - days * DAY_MS
        try:
            response = await _bybit_signed_get(
                http,
                signer,
                BYBIT_FILLS_PATH,
                {
                    "category": LINEAR,
                    "symbol": symbol,
                    "limit": "1",
                    "startTime": str(span_start),
                    "endTime": str(end_ms),
                },
            )
        except httpx.HTTPError as exc:
            return SpanProbe(days, "unknown", f"{describe_failure(exc)}")
        code, msg, _ = _bybit_envelope(response)
        if response.status_code != 200 or code is None:
            return SpanProbe(days, "unknown", f"HTTP {response.status_code}, unparseable body")
        if code == 0:
            return SpanProbe(days, "accepted", f"retCode=0 for a {days}d window")
        return SpanProbe(days, "refused", f"retCode={code} retMsg={msg!r} at {days}d")

    bisection = await bisect_max_accepted_span(span_candidates_days, probe_span)
    results["a"] = _span_result_to_verdict(bisection)
    results["b"] = await _safe_item(
        _bybit_pagination(http, signer, symbol, start_ms, end_ms, page_limit), "b"
    )
    results["c"] = await _safe_item(_bybit_weight_cost(http, signer, symbol, start_ms, end_ms), "c")
    results["d"] = await _safe_item(
        _bybit_liquidation_check(http, signer, symbol, start_ms, end_ms, page_limit), "d"
    )
    return results


# --- Binance -------------------------------------------------------------------


async def _binance_signed_get(
    http: httpx.AsyncClient,
    signer: BinanceSigner,
    path: str,
    params: Mapping[str, str] | None = None,
) -> httpx.Response:
    signed = signer.sign_get(path, params)
    return await http.get(signed.path_with_query, headers=dict(signed.headers))


def _binance_error(response: httpx.Response) -> tuple[int, str] | None:
    """``None`` when the body is not an error envelope. Binance rejects
    through the status line too, but a 200 body carrying a negative ``code``
    is a rejection just the same (same trap the fee/order scripts already
    name)."""
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int) and code < 0:
            return code, str(body.get("msg", ""))
    return None


async def _binance_clock_skew(http: httpx.AsyncClient) -> ItemVerdict:
    # Warm the connection first: the TLS handshake would otherwise sit
    # inside the measured round trip and widen its uncertainty.
    await http.get(BINANCE_SERVER_TIME_PATH)
    sent_ms = _epoch_ms(SystemClock().now())
    response = await http.get(BINANCE_SERVER_TIME_PATH)
    received_ms = _epoch_ms(SystemClock().now())
    try:
        body: Any = response.json()
    except ValueError:
        return ItemVerdict("unknown", f"HTTP {response.status_code}, non-JSON body")
    server_ms = body.get("serverTime") if isinstance(body, dict) else None
    if not isinstance(server_ms, int):
        return ItemVerdict("unknown", f"no integer serverTime in body: {body!r}")
    skew_ms, round_trip_ms = clock_skew_ms(server_ms, sent_ms, received_ms)
    return ItemVerdict(
        "answered",
        f"server - host = {skew_ms} ms +/- {round_trip_ms // 2} ms "
        f"(positive: venue ahead; round trip {round_trip_ms} ms)",
    )


async def _binance_key_acceptance(
    http: httpx.AsyncClient, signer: BinanceSigner, symbol: str, start_ms: int, end_ms: int
) -> ItemVerdict:
    response = await _binance_signed_get(
        http,
        signer,
        BINANCE_FILLS_PATH,
        {"symbol": symbol, "limit": "1", "startTime": str(start_ms), "endTime": str(end_ms)},
    )
    error = _binance_error(response)
    if response.status_code == 200 and error is None:
        return ItemVerdict("answered", "HTTP 200 -- this key is accepted on the fill endpoint")
    if error is not None:
        code, msg = error
        return ItemVerdict("refused", f"msg={msg!r}", code=str(code))
    return ItemVerdict(
        "refused",
        f"HTTP {response.status_code}: {response.text[:200]}",
        code=str(response.status_code),
    )


async def _binance_pagination(
    http: httpx.AsyncClient,
    signer: BinanceSigner,
    symbol: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
) -> ItemVerdict:
    plain = await _binance_signed_get(
        http,
        signer,
        BINANCE_FILLS_PATH,
        {
            "symbol": symbol,
            "limit": str(page_limit),
            "startTime": str(start_ms),
            "endTime": str(end_ms),
        },
    )
    plain_body: Any = plain.json() if plain.status_code == 200 else None
    plain_error = _binance_error(plain)
    plain_detail = (
        f"{len(plain_body)} entries (limit={page_limit})"
        if isinstance(plain_body, list)
        else f"HTTP {plain.status_code}, error={plain_error}"
    )

    combined = await _binance_signed_get(
        http,
        signer,
        BINANCE_FILLS_PATH,
        {
            "symbol": symbol,
            "limit": str(page_limit),
            "startTime": str(start_ms),
            "endTime": str(end_ms),
            "fromId": "0",
        },
    )
    combined_error = _binance_error(combined)
    combined_detail = (
        f"fromId + startTime/endTime together: HTTP {combined.status_code}, "
        f"error={combined_error}"
    )

    status: ItemStatus = "answered" if isinstance(plain_body, list) else "unknown"
    return ItemVerdict(status, f"{plain_detail}; {combined_detail}")


async def _binance_weight_cost(
    http: httpx.AsyncClient, signer: BinanceSigner, symbol: str, start_ms: int, end_ms: int
) -> ItemVerdict:
    params = {"symbol": symbol, "limit": "1", "startTime": str(start_ms), "endTime": str(end_ms)}
    first = await _binance_signed_get(http, signer, BINANCE_FILLS_PATH, params)
    second = await _binance_signed_get(http, signer, BINANCE_FILLS_PATH, params)
    cost = header_call_cost(
        _headers_map(first), _headers_map(second), BINANCE_USED_WEIGHT_1M_HEADER, "increasing"
    )
    if cost is None:
        return ItemVerdict(
            "unknown",
            f"{BINANCE_USED_WEIGHT_1M_HEADER} missing, unchanged (window reset between calls) "
            "or moved the wrong way",
        )
    return ItemVerdict("answered", f"{cost} weight per call to {BINANCE_FILLS_PATH}")


async def _binance_liquidation_check(
    http: httpx.AsyncClient, signer: BinanceSigner, symbol: str, start_ms: int, end_ms: int
) -> ItemVerdict:
    force_orders = await _binance_signed_get(
        http,
        signer,
        BINANCE_FORCE_ORDERS_PATH,
        {"symbol": symbol, "startTime": str(start_ms), "endTime": str(end_ms)},
    )
    force_error = _binance_error(force_orders)
    if force_orders.status_code != 200 or force_error is not None:
        detail = (
            f"forceOrders refused: code={force_error[0]} msg={force_error[1]!r}"
            if force_error is not None
            else f"forceOrders HTTP {force_orders.status_code}"
        )
        return ItemVerdict(
            "unknown", f"{detail} -- key may not permit this endpoint; UNKNOWN, not inferred"
        )
    force_body: Any = force_orders.json()
    if not isinstance(force_body, list) or not force_body:
        return ItemVerdict(
            "unknown", "no liquidation in history -- forceOrders returned no entries"
        )

    force_order_ids = {entry.get("orderId") for entry in force_body if isinstance(entry, dict)}

    fills = await _binance_signed_get(
        http,
        signer,
        BINANCE_FILLS_PATH,
        {"symbol": symbol, "startTime": str(start_ms), "endTime": str(end_ms), "limit": "1000"},
    )
    fills_error = _binance_error(fills)
    fills_body: Any = fills.json() if fills.status_code == 200 and fills_error is None else None
    if not isinstance(fills_body, list):
        return ItemVerdict(
            "unknown",
            f"{len(force_order_ids)} forceOrders in window, but userTrades could not be "
            "read to confirm",
        )

    matching = [
        entry
        for entry in fills_body
        if isinstance(entry, dict) and entry.get("orderId") in force_order_ids
    ]
    if not matching:
        return ItemVerdict(
            "unknown",
            f"{len(force_order_ids)} forceOrders in window but none matched an entry on the fill "
            "endpoint -- no liquidation FILL confirmed in history",
        )
    return ItemVerdict(
        "answered", f"{len(matching)} fill(s) matched a forceOrders orderId; orderId IS present"
    )


async def check_binance(
    http: httpx.AsyncClient,
    signer: BinanceSigner,
    symbol: str,
    now: datetime,
    span_candidates_days: Sequence[int],
    lookback_days: int,
    page_limit: int,
) -> dict[str, ItemVerdict]:
    """Binance's twin of ``check_bybit`` -- same gating: (e) unsigned and
    always attempted, (f) gates the four signed items."""
    results: dict[str, ItemVerdict] = {}
    end_ms = _epoch_ms(now)
    start_ms = end_ms - lookback_days * DAY_MS

    results["e"] = await _safe_item(_binance_clock_skew(http), "e")
    results["f"] = await _safe_item(
        _binance_key_acceptance(http, signer, symbol, start_ms, end_ms), "f"
    )
    if results["f"].status != "answered":
        blocked = ItemVerdict("unknown", "key not accepted on this endpoint -- see item (f)")
        results["a"] = results["b"] = results["c"] = results["d"] = blocked
        return results

    async def probe_span(days: int) -> SpanProbe:
        span_start = end_ms - days * DAY_MS
        try:
            response = await _binance_signed_get(
                http,
                signer,
                BINANCE_FILLS_PATH,
                {
                    "symbol": symbol,
                    "limit": "1",
                    "startTime": str(span_start),
                    "endTime": str(end_ms),
                },
            )
        except httpx.HTTPError as exc:
            return SpanProbe(days, "unknown", f"{describe_failure(exc)}")
        error = _binance_error(response)
        if response.status_code == 200 and error is None:
            return SpanProbe(days, "accepted", f"HTTP 200 for a {days}d window")
        if error is not None:
            code, msg = error
            return SpanProbe(days, "refused", f"code={code} msg={msg!r} at {days}d")
        return SpanProbe(days, "unknown", f"HTTP {response.status_code}, unparseable body")

    bisection = await bisect_max_accepted_span(span_candidates_days, probe_span)
    results["a"] = _span_result_to_verdict(bisection)
    results["b"] = await _safe_item(
        _binance_pagination(http, signer, symbol, start_ms, end_ms, page_limit), "b"
    )
    results["c"] = await _safe_item(
        _binance_weight_cost(http, signer, symbol, start_ms, end_ms), "c"
    )
    results["d"] = await _safe_item(
        _binance_liquidation_check(http, signer, symbol, start_ms, end_ms), "d"
    )
    return results


# --- entry point ---------------------------------------------------------------


def _print_results(results: Mapping[str, ItemVerdict]) -> None:
    for item in ITEM_ORDER:
        verdict = results.get(item)
        if verdict is not None:
            print(f"  {format_item_verdict(item, verdict)}")


async def _run(args: Args) -> int:
    settings = get_settings()
    clock = SystemClock()
    now = clock.now()

    print("Venue fill-window probe -- GET-only, places nothing")
    print(f"  symbol   {args.symbol}")
    print(f"  lookback {args.lookback_days}d")
    print(f"  span candidates (days) {list(args.span_candidates_days)}")

    print(f"\n=== BYBIT ({BYBIT_EXCHANGE}) ===")
    bybit_results: dict[str, ItemVerdict] = {}
    try:
        async with vault_credentials(settings, BYBIT_EXCHANGE) as vaulted:
            announce(vaulted, f"vault ({BYBIT_EXCHANGE})")
            bybit_signer = BybitSigner(
                BybitCredentials(api_key=vaulted.api_key, api_secret=vaulted.api_secret),
                clock,
                recv_window_ms=settings.bybit_recv_window_ms,
            )
            async with httpx.AsyncClient(
                base_url=settings.bybit_base_url, timeout=settings.bybit_timeout_seconds
            ) as http:
                bybit_results = await check_bybit(
                    http,
                    bybit_signer,
                    args.symbol,
                    now,
                    args.span_candidates_days,
                    args.lookback_days,
                    args.page_limit,
                )
    except Exception as exc:  # one venue's credential/transport failure must not
        # discard the other venue's results -- same rule as measure_reconciliation
        #_rate_limits.py's per-venue try/except.
        print(f"  FAILED before any per-item verdict: {describe_failure(exc)}")
    _print_results(bybit_results)

    print(f"\n=== BINANCE ({BINANCE_EXCHANGE}) ===")
    binance_results: dict[str, ItemVerdict] = {}
    try:
        async with vault_credentials(settings, BINANCE_EXCHANGE) as vaulted:
            announce(vaulted, f"vault ({BINANCE_EXCHANGE})")
            binance_signer = BinanceSigner(
                BinanceCredentials(api_key=vaulted.api_key, api_secret=vaulted.api_secret),
                clock,
                recv_window_ms=settings.binance_recv_window_ms,
            )
            async with httpx.AsyncClient(
                base_url=settings.binance_futures_base_url,
                timeout=settings.binance_timeout_seconds,
            ) as http:
                binance_results = await check_binance(
                    http,
                    binance_signer,
                    args.symbol,
                    now,
                    args.span_candidates_days,
                    args.lookback_days,
                    args.page_limit,
                )
    except Exception as exc:  # deliberately broad, for the same reason as above
        print(f"  FAILED before any per-item verdict: {describe_failure(exc)}")
    _print_results(binance_results)

    ok = bool(bybit_results) and bool(binance_results)
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    # Binance names a wallet "USDⓈ-M Futures", and a Windows console defaults
    # to cp1252, which cannot encode that character. Same guard every probe
    # in this directory carries.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
