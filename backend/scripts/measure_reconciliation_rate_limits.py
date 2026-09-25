"""Manual measurement: what rate-limit budget a reconciliation poll would spend.

This is NOT a test. It needs real API credentials and it talks to two live
exchanges, which is why it lives here and not under tests/ (CLAUDE.md rule 1).

It is GET-only. It places nothing, changes no setting, and touches no endpoint
that could.

**Why this exists.** The reconciliation job will call one endpoint per pool per
interval, forever. Choosing that interval from the venues' published limits
would be a guess in two ways, and both of them fail quietly:

  - A published limit is a ceiling for an anonymous reader. What is LEFT of it
    on this account, on this host, with ``balance.sync`` already running, is a
    different number and only the venue can report it.
  - The cost of a call is not stated anywhere this system can verify. Binance
    prices each endpoint in "weight" and reports only the RUNNING TOTAL, so the
    price of one call is a DIFFERENCE between two responses. It has to be
    measured; it cannot be looked up.

So this probe sends the exact calls reconciliation will send, and prints what
the venues answer about their own budgets. A guess cannot produce those
numbers, which is the whole reason the design refused to invent an interval.

**The two budgets are scoped differently, and that decides where to run this.**

  Binance  weight is counted PER IP. ``balance.sync``, this probe, and anything
           else on this address all draw on ONE pool.
  Bybit    the limit is counted PER API KEY, and per endpoint group:
           ``/v5/account/wallet-balance`` and ``/v5/position/list`` carry
           separate buckets.

So run this ON THE HOST THE WORKER RUNS ON. Measured anywhere else, the Binance
headroom belongs to an IP that is not carrying ``balance.sync``'s traffic, and
the number says nothing about production.

What it measures, per venue:

  BYBIT    ``GET /v5/position/list?category=linear&settleCoin=USDT`` -- the
           exact call ``BybitReadOnlyClient.positions()`` makes. Signed with
           the VAULT key, because that is the key ``balance.sync`` signs with
           and the budget belongs to the key.
  BINANCE  ``GET /fapi/v3/positionRisk`` with NO symbol -- every position in
           one call, which is what reconciliation needs and is NOT what
           ``BinanceReadOnlyClient.position_for(symbol)`` sends today. Signed
           with the VAULT key (design decision 18, ONE key per exchange --
           superseding the `.env` read-only key this comment used to name),
           the same key ``balance.sync`` and every other Binance read now use.

Each endpoint is called more than once on purpose: one response reports a
running total, two report a cost.

**Why it does not use the read clients.** ``BinanceTransport._send`` and
``BybitTransport._send`` both return the parsed payload and drop the response
object, so the rate-limit headers are unreachable through every client built on
them. Widening a transport that production depends on, for a measurement, would
be the wrong trade. Instead this signs through the production SIGNERS -- the
exact same bytes, the same recv window, the same clock -- and sends them with a
raw ``httpx.AsyncClient``, so the response headers stay in hand.

Usage:
    cd backend
    uv run python scripts/measure_reconciliation_rate_limits.py
    uv run python scripts/measure_reconciliation_rate_limits.py --samples 3
    uv run python scripts/measure_reconciliation_rate_limits.py --pools 2
"""

import argparse
import asyncio
import io
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from typing import Any

import httpx
from probe_credentials import announce, vault_credentials

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.binance import EXCHANGE as BINANCE_EXCHANGE

# The production paths, imported rather than retyped: a probe that measures a
# path production does not call measures nothing.
from strategy_manager.shared.infrastructure.binance.read_client import (
    ACCOUNT_PATH,
    POSITION_RISK_PATH,
)
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.bybit import EXCHANGE as BYBIT_EXCHANGE
from strategy_manager.shared.infrastructure.bybit.read_client import (
    LINEAR,
    POSITIONS_PATH,
    UNIFIED,
    WALLET_BALANCE_PATH,
)
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.clock import SystemClock

DEFAULT_SETTLE_COIN = "USDT"

# Two responses are the minimum that can report a cost rather than a total.
MIN_SAMPLES = 2

# Public, unsigned, and the only place either venue states its own ceiling in a
# form this system can read back.
EXCHANGE_INFO_PATH = "/fapi/v1/exchangeInfo"
REQUEST_WEIGHT = "REQUEST_WEIGHT"

# Response headers worth printing, matched case-insensitively by PREFIX rather
# than by exact name. The whole vendor family is printed, not only the three
# headers this was written for: a budget header nobody anticipated is exactly
# the one a fixed list would drop, and a probe exists to be told what it did
# not already know.
BYBIT_HEADER_PREFIXES = ("x-bapi-limit", "x-bapi-rate")
BINANCE_HEADER_PREFIXES = ("x-mbx-used-weight", "x-mbx-order-count")

BINANCE_USED_WEIGHT_1M = "x-mbx-used-weight-1m"
BYBIT_LIMIT = "x-bapi-limit"
BYBIT_LIMIT_STATUS = "x-bapi-limit-status"

# How much of a venue's budget this system is willing to spend on POLLING.
# The remaining 80% is not spare. Order placement, fill settlement and retries
# draw on the same allowance, and they arrive in BURSTS -- at exactly the
# moments when being throttled costs the most money.
POLLING_BUDGET_FRACTION = Decimal("0.20")

SECONDS_PER_MINUTE = Decimal(60)


@dataclass(frozen=True, slots=True)
class Observation:
    """One response, kept as evidence rather than as a parsed conclusion."""

    label: str
    request: str
    status: int
    headers: tuple[tuple[str, str], ...]
    detail: str


def _matching_headers(
    response: httpx.Response, prefixes: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    """Every response header whose name starts with one of ``prefixes``.

    Read off ``raw`` rather than the mapping so the venue's OWN capitalisation
    survives: httpx lowercases keys on the way out, and this output is meant to
    be quotable evidence of what the venue sent.
    """
    found: list[tuple[str, str]] = []
    for name, value in response.headers.raw:
        decoded = name.decode("latin-1")
        if decoded.lower().startswith(prefixes):
            found.append((decoded, value.decode("latin-1")))
    return tuple(found)


def _header(observation: Observation, name: str) -> str | None:
    for key, value in observation.headers:
        if key.lower() == name:
            return value
    return None


def _int_header(observation: Observation, name: str) -> int | None:
    """``None`` means "not reported or not a number", never zero.

    A missing budget header read as zero would look like an exhausted limit,
    and an unreadable one read as zero would look like a free call. Both are
    conclusions this probe must refuse to reach on its own.
    """
    raw = _header(observation, name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _bybit_detail(response: httpx.Response) -> str:
    """Bybit answers a rejection with HTTP 200 and a non-zero ``retCode``, so
    the status line alone would read a refusal as an answer."""
    try:
        envelope = response.json()
    except ValueError:
        return "non-JSON body"
    if not isinstance(envelope, dict):
        return "non-object body"
    code = envelope.get("retCode")
    if code != 0:
        return f"REJECTED retCode={code!r} retMsg={envelope.get('retMsg')!r}"
    result = envelope.get("result")
    entries = result.get("list") if isinstance(result, dict) else None
    if isinstance(entries, list):
        return f"retCode=0, {len(entries)} entries in result.list"
    return "retCode=0"


def _binance_detail(response: httpx.Response) -> str:
    """Binance rejects through the status line, but a 200 body carrying a
    negative ``code`` is a rejection too."""
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code} with a non-JSON body"
    if isinstance(payload, dict):
        code = payload.get("code")
        if isinstance(code, int) and code < 0:
            return f"REJECTED code={code} msg={payload.get('msg')!r}"
        return f"object body, keys {sorted(payload)[:6]}"
    if isinstance(payload, list):
        return f"{len(payload)} entries"
    return f"{type(payload).__name__} body"


async def _bybit_call(
    http: httpx.AsyncClient,
    signer: BybitSigner,
    label: str,
    path: str,
    params: Mapping[str, str],
) -> Observation:
    signed = signer.sign_get(path, params)
    response = await http.get(signed.path_with_query, headers=dict(signed.headers))
    return Observation(
        label=label,
        request=f"GET {signed.path_with_query}",
        status=response.status_code,
        headers=_matching_headers(response, BYBIT_HEADER_PREFIXES),
        detail=_bybit_detail(response),
    )


async def _binance_signed_call(
    http: httpx.AsyncClient,
    signer: BinanceSigner,
    label: str,
    path: str,
) -> Observation:
    signed = signer.sign_get(path)
    response = await http.get(signed.path_with_query, headers=dict(signed.headers))
    # The signed query carries the signature; the path alone is what belongs in
    # output that gets pasted into a change document.
    return Observation(
        label=label,
        request=f"GET {path} (signed, no symbol parameter)",
        status=response.status_code,
        headers=_matching_headers(response, BINANCE_HEADER_PREFIXES),
        detail=_binance_detail(response),
    )


def _request_weight_limit(payload: Any) -> tuple[int, str] | None:
    """Binance's own statement of the ceiling, from ``exchangeInfo``.

    Taken from the venue rather than from documentation for the same reason
    every other number here is measured: the published figure is what applies
    to somebody, and this asks what applies to us.
    """
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rateLimits")
    if not isinstance(limits, list):
        return None
    for entry in limits:
        if not isinstance(entry, dict) or entry.get("rateLimitType") != REQUEST_WEIGHT:
            continue
        limit = entry.get("limit")
        if not isinstance(limit, int):
            continue
        return limit, f"{entry.get('intervalNum')} {entry.get('interval')}"
    return None


async def _measure_bybit(
    settings: Settings,
    credentials: BybitCredentials,
    settle_coin: str,
    samples: int,
) -> list[Observation]:
    """The reconciliation call, plus the call ``balance.sync`` already makes.

    Both are measured because Bybit buckets its limits per endpoint group, and
    the only way to show that the two do not share a budget is to print the
    limit each one reports for itself.
    """
    signer = BybitSigner(
        credentials, SystemClock(), recv_window_ms=settings.bybit_recv_window_ms
    )
    observations: list[Observation] = []
    async with httpx.AsyncClient(
        base_url=settings.bybit_base_url, timeout=settings.bybit_timeout_seconds
    ) as http:
        observations.append(
            await _bybit_call(
                http,
                signer,
                "balance.sync's existing call",
                WALLET_BALANCE_PATH,
                {"accountType": UNIFIED},
            )
        )
        for sample in range(1, samples + 1):
            observations.append(
                await _bybit_call(
                    http,
                    signer,
                    f"reconciliation's call, sample {sample}",
                    POSITIONS_PATH,
                    {"category": LINEAR, "settleCoin": settle_coin},
                )
            )
    return observations


async def _measure_binance(
    settings: Settings, credentials: BinanceCredentials, samples: int
) -> tuple[list[Observation], tuple[int, str] | None]:
    """The ceiling, ``balance.sync``'s call, then the reconciliation call twice.

    Order matters. The ceiling is read first so the used-weight figures that
    follow can be read against it, and the reconciliation call is repeated so
    its COST appears as a difference rather than as a total.
    """
    signer = BinanceSigner(
        credentials, SystemClock(), recv_window_ms=settings.binance_recv_window_ms
    )
    observations: list[Observation] = []
    async with httpx.AsyncClient(
        base_url=settings.binance_futures_base_url,
        timeout=settings.binance_timeout_seconds,
    ) as http:
        # Public: no signature, and the only endpoint that states the ceiling.
        info = await http.get(EXCHANGE_INFO_PATH)
        try:
            weight_limit = _request_weight_limit(info.json())
        except ValueError:
            weight_limit = None
        observations.append(
            Observation(
                label="the venue's own ceiling (public)",
                request=f"GET {EXCHANGE_INFO_PATH}",
                status=info.status_code,
                headers=_matching_headers(info, BINANCE_HEADER_PREFIXES),
                detail=(
                    f"{REQUEST_WEIGHT} limit {weight_limit[0]} per {weight_limit[1]}"
                    if weight_limit
                    else f"no {REQUEST_WEIGHT} limit found in rateLimits"
                ),
            )
        )

        observations.append(
            await _binance_signed_call(
                http, signer, "balance.sync's existing call", ACCOUNT_PATH
            )
        )
        for sample in range(1, samples + 1):
            observations.append(
                await _binance_signed_call(
                    http,
                    signer,
                    f"reconciliation's call, sample {sample}",
                    POSITION_RISK_PATH,
                )
            )
    return observations, weight_limit


def _render(observations: list[Observation]) -> None:
    for index, observation in enumerate(observations, start=1):
        print(f"\n  [{index}] {observation.label}")
        print(f"      {observation.request}")
        print(f"      HTTP {observation.status} -- {observation.detail}")
        if not observation.headers:
            print("      NO rate-limit headers on this response")
            continue
        for name, value in observation.headers:
            print(f"      {name}: {value}")


def _weight_deltas(observations: list[Observation]) -> list[tuple[int, int | None]]:
    """The cost of call N, as the change in the running total it reports.

    ``None`` where the difference cannot be read: an absent header, or a
    negative step, which means the one-minute window rolled over between the
    two responses and the pair proves nothing.
    """
    deltas: list[tuple[int, int | None]] = []
    previous: int | None = None
    for index, observation in enumerate(observations, start=1):
        used = _int_header(observation, BINANCE_USED_WEIGHT_1M)
        if used is None or previous is None or used < previous:
            deltas.append((index, None))
        else:
            deltas.append((index, used - previous))
        previous = used
    return deltas


def _seconds(value: Decimal) -> Decimal:
    """Rounded UP, always. A longer interval spends less budget, so up is the
    side of this number that cannot cause the failure being avoided."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_UP)


def _interpret_bybit(
    observations: list[Observation], pools: int, sync_interval: Decimal
) -> Decimal | None:
    """What the measured Bybit headers mean, and the interval they permit."""
    print("\n--- Bybit: what the headers say ---")
    if len(observations) < 2:
        print("  not enough responses to interpret")
        return None

    sync, *reconciliation = observations
    sync_limit = _int_header(sync, BYBIT_LIMIT)
    limit = _int_header(reconciliation[0], BYBIT_LIMIT)
    status = _int_header(reconciliation[-1], BYBIT_LIMIT_STATUS)

    reset = _header(reconciliation[-1], "x-bapi-limit-reset-timestamp")
    print(f"  {POSITIONS_PATH}")
    print(f"    X-Bapi-Limit        {limit}  (requests allowed in the window)")
    print(f"    X-Bapi-Limit-Status {status}  (left in the window, after this probe)")
    print(f"    reset timestamp     {reset}  (ms; how far ahead the window ends)")
    print(f"  {WALLET_BALANCE_PATH}  (balance.sync)")
    print(f"    X-Bapi-Limit        {sync_limit}")
    print(
        "  Bybit buckets per endpoint group and counts per API KEY. The two "
        "limits above\n  are separate allowances: balance.sync every "
        f"{sync_interval}s does NOT spend the\n  budget reconciliation draws on."
    )

    if limit is None or limit <= 0:
        print("  no usable X-Bapi-Limit, so no interval is derived from Bybit.")
        return None

    allowance = POLLING_BUDGET_FRACTION * Decimal(limit)
    shortest = _seconds(Decimal(pools) / allowance)
    # Bybit documents this bucket as a ONE SECOND window. The reset timestamp
    # printed above is what confirms it: if it is not roughly a second ahead of
    # now, the window is not what this arithmetic assumes and the floor below
    # is wrong by exactly that factor.
    print("\n  arithmetic (assuming the documented one-second window):")
    print(f"    limit                      {limit} requests/second")
    print(
        f"    polling allowance ({POLLING_BUDGET_FRACTION:%})     "
        f"{POLLING_BUDGET_FRACTION} x {limit} = {allowance} requests/second"
    )
    print(f"    reconciliation needs       {pools} request(s) per interval")
    print(f"    shortest interval          {pools} / {allowance} = {shortest} s")
    return shortest


def _interpret_binance(
    observations: list[Observation],
    weight_limit: tuple[int, str] | None,
    sync_interval: Decimal,
) -> Decimal | None:
    """What the measured Binance weights mean, and the interval they permit."""
    print("\n--- Binance: what the headers say ---")
    deltas = _weight_deltas(observations)
    for index, delta in deltas:
        observation = observations[index - 1]
        used = _int_header(observation, BINANCE_USED_WEIGHT_1M)
        cost = "?" if delta is None else str(delta)
        print(f"  [{index}] used-weight-1m now {used}, this call cost {cost}")
    print(
        "  A cost is the DIFFERENCE between two responses, so it includes any "
        "other\n  traffic this IP made in between -- balance.sync included. "
        "That is a feature:\n  the weight budget is per IP, and this is what "
        "the budget actually sees."
    )

    # Index 2 is balance.sync's call, 3 onward are the reconciliation samples.
    sync_weight = deltas[1][1] if len(deltas) > 1 else None
    recon_weights = [delta for index, delta in deltas[2:] if delta is not None]
    recon_weight = max(recon_weights) if recon_weights else None

    if weight_limit is None or sync_weight is None or recon_weight is None:
        print(
            "\n  INCOMPLETE: the ceiling, balance.sync's cost or reconciliation's "
            "cost\n  could not be read. No interval is derived from a measurement "
            "that did not\n  happen -- re-run it rather than assume a number."
        )
        return None

    limit, window = weight_limit
    allowance = POLLING_BUDGET_FRACTION * Decimal(limit)
    sync_calls = SECONDS_PER_MINUTE / sync_interval
    sync_per_minute = sync_calls * Decimal(sync_weight)
    left = allowance - sync_per_minute

    print("\n  arithmetic:")
    print(f"    budget                     {limit} weight per {window} (venue-reported)")
    print(
        f"    polling allowance ({POLLING_BUDGET_FRACTION:%})     "
        f"{POLLING_BUDGET_FRACTION} x {limit} = {allowance} weight/minute"
    )
    print(
        f"    balance.sync every {sync_interval}s    {SECONDS_PER_MINUTE}/{sync_interval}"
        f" = {sync_calls} calls/min x {sync_weight} = {sync_per_minute} weight/minute"
    )
    print(f"    left for reconciliation    {allowance} - {sync_per_minute} = {left}")
    print(f"    one reconciliation call    {recon_weight} weight (all positions, one call)")

    if left <= 0:
        print(
            "    NO HEADROOM: balance.sync alone already fills the polling "
            "allowance.\n    Reconciliation cannot be added at this interval "
            "without raising the\n    allowance or slowing balance.sync. That is "
            "a decision, not an arithmetic\n    result, so no number is offered."
        )
        return None

    affordable = left / Decimal(recon_weight)
    shortest = _seconds(SECONDS_PER_MINUTE / affordable)
    print(f"    calls affordable           {left} / {recon_weight} = {affordable} per minute")
    print(f"    shortest interval          {SECONDS_PER_MINUTE} / {affordable} = {shortest} s")
    return shortest


def _recommend(bybit: Decimal | None, binance: Decimal | None) -> None:
    print("\n--- what this recommends ---")
    candidates = [value for value in (bybit, binance) if value is not None]
    if not candidates:
        print(
            "  Nothing. Neither venue produced a usable measurement, and an "
            "interval\n  invented here would be exactly the guess this phase "
            "exists to replace."
        )
        return

    binding = max(candidates)
    print(f"  Bybit permits at least   {bybit if bybit is not None else 'unmeasured'} s")
    print(f"  Binance permits at least {binance if binance is not None else 'unmeasured'} s")
    print(f"  The binding one is       {binding} s")
    print(
        "\n  That is the floor the measured budgets allow while keeping "
        f"{POLLING_BUDGET_FRACTION:%} of each\n  venue's allowance for polling and the rest "
        "for orders, settlement and retries.\n  How STALE a fill may be is a separate "
        "question, and it is the one that should\n  choose the interval above this floor."
    )
    print(
        "\n  This is a recommendation from ONE observation, on one host, at one "
        "moment,\n  with whatever load the account was carrying. It is evidence, "
        "not a decision:\n  the owner chooses the literal that gets committed."
    )


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--settle-coin",
        default=DEFAULT_SETTLE_COIN,
        help="Bybit filters positions by settlement currency, which is also how "
        "this system pools capital (default: USDT)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=MIN_SAMPLES,
        help=f"how many times to send the reconciliation call (minimum {MIN_SAMPLES}: "
        "one response reports a total, two report a cost)",
    )
    parser.add_argument(
        "--pools",
        type=int,
        default=1,
        help="how many pools reconciliation would poll per interval on Bybit, "
        "which calls once per settlement currency (default: 1). Binance returns "
        "every position in one call, so its arithmetic does not use this.",
    )
    args = parser.parse_args()

    if args.samples < MIN_SAMPLES:
        print(f"--samples must be at least {MIN_SAMPLES}", file=sys.stderr)
        return 2
    if args.pools < 1:
        print("--pools must be at least 1", file=sys.stderr)
        return 2

    settings = get_settings()
    sync_interval = Decimal(str(settings.balance_sync_interval_seconds))

    print("Reconciliation rate-limit measurement")
    print(f"  Bybit base URL:      {settings.bybit_base_url}")
    print(f"  Binance futures URL: {settings.binance_futures_base_url}")
    print(f"  balance.sync interval: {sync_interval}s (settings.balance_sync_interval_seconds)")
    print("  This probe is GET-only: it places nothing and changes no setting.")
    print(
        "\n  Binance counts weight PER IP; Bybit counts requests PER API KEY.\n"
        "  RUN THIS ON THE HOST THE WORKER RUNS ON. Anywhere else, the Binance\n"
        "  headroom is measured against an address that is not carrying\n"
        "  balance.sync's traffic, and the number is not about production."
    )

    bybit_observations: list[Observation] = []
    binance_observations: list[Observation] = []
    weight_limit: tuple[int, str] | None = None

    print(f"\n=== BYBIT ({BYBIT_EXCHANGE}) ===")
    try:
        # The VAULT key, because that is the one balance.sync signs with and a
        # per-key budget measured on a different key is a different budget.
        async with vault_credentials(settings, BYBIT_EXCHANGE) as vaulted:
            announce(vaulted, f"vault ({BYBIT_EXCHANGE})")
            bybit_observations = await _measure_bybit(
                settings,
                BybitCredentials(
                    api_key=vaulted.api_key, api_secret=vaulted.api_secret
                ),
                args.settle_coin.upper(),
                args.samples,
            )
        _render(bybit_observations)
    except Exception as exc:
        # Deliberately broad, and only here: one venue failing must not discard
        # the other venue's measurement, and a partial answer is still evidence.
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    print(f"\n=== BINANCE ({BINANCE_EXCHANGE}) ===")
    try:
        # The VAULT key, same as Bybit above (design decision 18: ONE key per
        # exchange) -- and the same key balance.sync now signs with, so this
        # measurement is against the budget that key actually spends.
        async with vault_credentials(settings, BINANCE_EXCHANGE) as vaulted:
            announce(vaulted, f"vault ({BINANCE_EXCHANGE})")
            binance = BinanceCredentials(
                api_key=vaulted.api_key, api_secret=vaulted.api_secret
            )
            binance_observations, weight_limit = await _measure_binance(
                settings, binance, args.samples
            )
        _render(binance_observations)
    except Exception as exc:
        # Broad for the same reason as the Bybit block above.
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    bybit_floor = (
        _interpret_bybit(bybit_observations, args.pools, sync_interval)
        if bybit_observations
        else None
    )
    binance_floor = (
        _interpret_binance(binance_observations, weight_limit, sync_interval)
        if binance_observations
        else None
    )
    _recommend(bybit_floor, binance_floor)

    return 0 if bybit_observations and binance_observations else 1


if __name__ == "__main__":
    # Binance names a wallet "USDⓈ-M Futures", and a Windows console defaults
    # to cp1252, which cannot encode that character. The same guard every probe
    # in this directory carries, for the same reason.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
