"""GET-only probe P6 (task 8a.0a): is a Binance key WITHOUT "Enable Futures"
refused on signed fapi READ endpoints, and does ``canTrade`` on
``GET /fapi/v2|v3/account`` track the key's permission?

Two keys are compared:

1. **The vault key** -- trade-enabled, loaded from the encrypted vault through
   ``probe_credentials.vault_credentials``, the same path
   ``check_key_permissions.py`` uses.
2. **A temporary key** with only "Enable Reading", read from the process
   environment: ``BINANCE_PROBE_API_KEY`` and ``BINANCE_PROBE_API_SECRET``.
   If either is missing the vault key runs alone; that is not a failure.

**GET only, structurally.** ``_get`` is the only function that touches the
network. It checks the path against the hard-coded ``ALLOWED_PATHS`` and always
calls ``http.get``; there is no other request call in this module. The probe
never places an order and changes no setting.

**Never prints a payload.** Per (key, path) it prints the key label with the
last four characters, the HTTP status, and Binance's ``code`` and ``msg`` when
present. Account endpoints add ONLY ``canTrade``/``canDeposit``/``canWithdraw``;
balance and positionRisk add ONLY an entry count; apiTradingStatus adds ONLY
its top-level key names. Transport errors print the exception class and a
short message, never the request URL (the signature travels in it).

Run on the VPS, from a session where the temporary key is typed silently so it
never touches disk or shell history (values are never echoed):

    cd /opt/strategy-manager/app/backend
    read -rs -p "temp key: " BINANCE_PROBE_API_KEY; echo
    read -rs -p "temp secret: " BINANCE_PROBE_API_SECRET; echo
    export BINANCE_PROBE_API_KEY BINANCE_PROBE_API_SECRET
    sudo -u strategy -H env \\
        BINANCE_PROBE_API_KEY="$BINANCE_PROBE_API_KEY" \\
        BINANCE_PROBE_API_SECRET="$BINANCE_PROBE_API_SECRET" \\
        /opt/strategy-manager/.local/bin/uv run python \\
        scripts/probe_binance_futures_permission.py
    unset BINANCE_PROBE_API_KEY BINANCE_PROBE_API_SECRET

Afterwards, DELETE the temporary key on Binance.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from probe_credentials import vault_credentials

from strategy_manager.accounts.infrastructure.credential_vault import CredentialNotFound
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.alert_redaction import redact
from strategy_manager.shared.infrastructure.binance import EXCHANGE as BINANCE_EXCHANGE
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.clock import SystemClock

ENV_KEY = "BINANCE_PROBE_API_KEY"
ENV_SECRET = "BINANCE_PROBE_API_SECRET"

ACCOUNT_V3 = "/fapi/v3/account"
ACCOUNT_V2 = "/fapi/v2/account"
BALANCE = "/fapi/v3/balance"
POSITION_RISK = "/fapi/v3/positionRisk"
TRADING_STATUS = "/fapi/v1/apiTradingStatus"
PERMISSIONS = "/fapi/v1/account/permissions"  # expected not to exist

ALLOWED_PATHS: tuple[str, ...] = (
    ACCOUNT_V3,
    ACCOUNT_V2,
    BALANCE,
    POSITION_RISK,
    TRADING_STATUS,
    PERMISSIONS,
)
# The reads whose refusal answers the question; the last two are informational.
_CORE_PATHS = (ACCOUNT_V3, ACCOUNT_V2, BALANCE, POSITION_RISK)
_ACCOUNT_PATHS = (ACCOUNT_V3, ACCOUNT_V2)
_CAN_FIELDS = ("canTrade", "canDeposit", "canWithdraw")
_MSG_LIMIT = 200


@dataclass(frozen=True, slots=True, repr=False)
class KeySpec:
    kind: str  # "vault" or "temporary read-only"
    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        return f"KeySpec(kind={self.kind!r}, api_key='***{self.api_key[-4:]}')"

    @property
    def mask(self) -> str:
        return f"***{self.api_key[-4:]}"

    @property
    def label(self) -> str:
        return f"{self.kind} key {self.mask}"

    @property
    def short(self) -> str:
        return "vault" if self.kind == "vault" else "read-only"


@dataclass(frozen=True, slots=True)
class PathResult:
    path: str
    ok: bool
    detail: str
    code: int | None = None
    can_trade: bool | None = None


def load_probe_specs(vault_key: str, vault_secret: str, env: Mapping[str, str]) -> list[KeySpec]:
    """The vault key always; the temporary key only when BOTH variables are set."""
    specs = [KeySpec("vault", vault_key, vault_secret)]
    temp_key, temp_secret = env.get(ENV_KEY, ""), env.get(ENV_SECRET, "")
    if temp_key and temp_secret:
        specs.append(KeySpec("temporary read-only", temp_key, temp_secret))
    else:
        print(f"No temporary key ({ENV_KEY} / {ENV_SECRET} not both set): vault key runs alone.")
    return specs


async def _get(http: httpx.AsyncClient, signer: BinanceSigner, path: str) -> httpx.Response:
    """The ONLY request call in this module. GET, allowlisted paths, nothing else."""
    if path not in ALLOWED_PATHS:
        raise ValueError(f"{path} is not in the GET allowlist")
    signed = signer.sign_get(path)
    return await http.get(signed.path_with_query, headers=dict(signed.headers))


def _scrub(text: str, spec: KeySpec) -> str:
    for secret in (spec.api_key, spec.api_secret):
        text = text.replace(secret, "***")
    return redact(text)[:_MSG_LIMIT]


def _describe_transport_error(exc: BaseException, spec: KeySpec) -> str:
    message = _scrub(str(exc), spec)
    if "://" in message or "signature" in message.lower() or "timestamp" in message.lower():
        message = "message withheld, it may echo the request URL"
    return f"{type(exc).__name__}: {message}"


def _error_envelope(body: Any) -> tuple[int, str] | None:
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int) and code < 0:
            return code, str(body.get("msg", ""))
    return None


def _summarise(path: str, response: httpx.Response, spec: KeySpec) -> PathResult:
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    status = response.status_code
    error = _error_envelope(body)
    if status != 200 or error is not None:
        if error is None:
            return PathResult(path, False, f"HTTP {status}")
        code, msg = error
        return PathResult(path, False, f"HTTP {status} code={code} msg={_scrub(msg, spec)!r}", code)
    if path in _ACCOUNT_PATHS and isinstance(body, dict):
        fields = {name: body.get(name) for name in _CAN_FIELDS}
        text = " ".join(f"{name}={value}" for name, value in fields.items())
        can_trade = fields["canTrade"]
        return PathResult(
            path,
            True,
            f"HTTP {status} {text}",
            can_trade=can_trade if isinstance(can_trade, bool) else None,
        )
    if path in (BALANCE, POSITION_RISK) and isinstance(body, list):
        return PathResult(path, True, f"HTTP {status} entries={len(body)}")
    if path == TRADING_STATUS and isinstance(body, dict):
        return PathResult(path, True, f"HTTP {status} keys={sorted(body)}")
    return PathResult(path, True, f"HTTP {status}")


async def _probe_key(
    spec: KeySpec, http: httpx.AsyncClient, signer: BinanceSigner
) -> list[PathResult]:
    print(f"Signing as {spec.label}")
    results: list[PathResult] = []
    for path in ALLOWED_PATHS:
        try:
            result = _summarise(path, await _get(http, signer, path), spec)
        except Exception as exc:  # one failed call must not hide the rest
            result = PathResult(path, False, _describe_transport_error(exc, spec))
        print(f"  [{spec.label}] GET {path} -> {result.detail}")
        results.append(result)
    return results


def _core_state(results: list[PathResult]) -> tuple[bool, str, bool | None]:
    """(reads OK, refusal description, canTrade) over the core reads."""
    core = [r for r in results if r.path in _CORE_PATHS]
    failing = [r for r in core if not r.ok]
    can_trade = next((r.can_trade for r in core if r.can_trade is not None), None)
    if not failing:
        return True, "", can_trade
    coded = next((r.code for r in failing if r.code is not None), None)
    return False, str(coded) if coded is not None else "without a Binance code", can_trade


def _summary_line(spec: KeySpec, results: list[PathResult]) -> str:
    reads_ok, refusal, can_trade = _core_state(results)
    if reads_ok:
        return f"{spec.short} {spec.mask}: reads OK, canTrade={can_trade}"
    return f"{spec.short} {spec.mask}: reads refused {refusal}"


def _verdict(specs: list[KeySpec], all_results: list[list[PathResult]]) -> str:
    if len(specs) < 2:
        return "VERDICT: not answered, no temporary key was supplied."
    vault_ok, _, vault_trade = _core_state(all_results[0])
    temp_ok, temp_refusal, temp_trade = _core_state(all_results[1])
    if not vault_ok:
        return "VERDICT: inconclusive, the vault key itself was refused on the fapi reads."
    if not temp_ok:
        return (
            "VERDICT: a key without Enable Futures is refused on fapi reads "
            f"({temp_refusal}); canTrade could not be compared."
        )
    if vault_trade is None or temp_trade is None:
        return "VERDICT: read-only key NOT refused on fapi reads; canTrade unreadable."
    if vault_trade != temp_trade:
        return (
            "VERDICT: read-only key NOT refused on fapi reads; canTrade differed "
            f"(vault={vault_trade}, read-only={temp_trade})."
        )
    return (
        "VERDICT: read-only key NOT refused on fapi reads; canTrade did NOT differ "
        f"(both {vault_trade})."
    )


async def run_probe(
    specs: list[KeySpec],
    *,
    base_url: str = "https://fapi.binance.com",
    recv_window_ms: int = 5000,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    print("Binance futures permission probe -- GET-only, places nothing, changes no setting")
    clock = SystemClock()
    all_results: list[list[PathResult]] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, transport=transport) as http:
        for spec in specs:
            signer = BinanceSigner(
                BinanceCredentials(api_key=spec.api_key, api_secret=spec.api_secret),
                clock,
                recv_window_ms=recv_window_ms,
            )
            all_results.append(await _probe_key(spec, http, signer))
    print("\nSUMMARY")
    for spec, results in zip(specs, all_results, strict=True):
        print(_summary_line(spec, results))
    print(_verdict(specs, all_results))
    return 0


async def _main() -> int:
    settings = get_settings()
    try:
        async with vault_credentials(settings, BINANCE_EXCHANGE) as vaulted:
            specs = load_probe_specs(vaulted.api_key, vaulted.api_secret, os.environ)
            return await run_probe(
                specs,
                base_url=settings.binance_futures_base_url,
                recv_window_ms=settings.binance_recv_window_ms,
            )
    except (CredentialNotFound, InvariantViolation) as exc:
        print(f"No usable vault key for {BINANCE_EXCHANGE}: {type(exc).__name__}")
        return 1


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
