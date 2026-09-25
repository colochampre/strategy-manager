"""GET-only probe: what each exchange key is allowed to do (design decision 3,
unit 1a). Answers, per venue, the five items owner-decisions.md decision 8 and
decision 18 need BEFORE any refusal rule in ``key_policy.py`` is written:

  P1  Bybit withdraw shape        -- does ``permissions.Wallet`` carry
                                      ``Withdraw`` (8b)?
  P2  Bybit trade capability      -- which field proves "can trade linear
                                      perpetuals" (``readOnly``,
                                      ``ContractTrade``, ``Derivatives``)?
  P3  Binance ``apiRestrictions`` -- ``enableWithdrawals`` (8b),
                                      ``enableFutures`` (trade capability),
                                      plus the shown-only transfer/IP fields.
  P4  Live reads with the VAULT key -- Bybit ``wallet-balance UNIFIED``;
                                      Binance ``account``, ``positionRisk``,
                                      ``symbolConfig``. Gates PR 3's deploy:
                                      every Binance read that moves off
                                      ``.env`` must first succeed with the
                                      vault key.
  P5  Binding / expiry            -- Bybit ``ips``/``expiredAt``/
                                      ``deadlineDay``; Binance ``ipRestrict``/
                                      ``tradingAuthorityExpirationTime``.
                                      Informational only; shown in Settings.

Places nothing, changes no setting -- the HTTP helper below (``GetOnlyTransport``)
refuses any method other than GET structurally, not by convention.

**Never prints a secret.** Bybit's ``query-api`` payload echoes the key back
under an ``apiKey`` field, so every payload is redacted before it is printed:
any field named ``apiKey``/``secret`` and any string equal to a key or secret
in use, down to the last 4 (CLAUDE.md rule 8). Every raised exception is
routed through ``alert_redaction.redact`` for the same reason.

**Keys, and nowhere else.** Loaded ONLY from the vault
(``probe_credentials.vault_credentials``) and, for their last use before PR 3
retires them, the ``.env`` Bybit (``***Swka``) and Binance read keys via each
venue's ``credentials_from_settings``. There is no prompt: a key stored
nowhere is simply absent, and the item that needed it prints UNKNOWN naming
what is missing, rather than asking anyone to paste a credential into a
terminal. Before every call, ``format_signing_line`` prints
``Signing as ***last4 (from the source)``.

Usage (from ``backend/``):
    uv run python scripts/check_key_permissions.py

**Exact VPS run command** (run AFTER this PR is merged and pulled; no restart
needed -- this is a read-only script with no importers in ``src/``):

    cd /opt/strategy-manager/app/backend && \\
    sudo -u strategy -H /opt/strategy-manager/.local/bin/uv run python \\
        scripts/check_key_permissions.py

Paste the output into ``openspec/changes/operator-panel/tasks.md`` §
"PR 1 -- Probe results". No line of ``key_policy.py`` is written before that
section carries P1-P3; PR 3 does not deploy before it carries P4.
"""

from __future__ import annotations

import asyncio
import io
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from probe_credentials import vault_credentials

from strategy_manager.accounts.infrastructure.credential_vault import CredentialNotFound
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.alert_redaction import redact
from strategy_manager.shared.infrastructure.binance import EXCHANGE as BINANCE_EXCHANGE
from strategy_manager.shared.infrastructure.binance.factory import (
    credentials_from_settings as binance_env_credentials,
)
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.bybit import EXCHANGE as BYBIT_EXCHANGE
from strategy_manager.shared.infrastructure.bybit.factory import (
    credentials_from_settings as bybit_env_credentials,
)
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials, BybitSigner
from strategy_manager.shared.infrastructure.clock import SystemClock

BYBIT_QUERY_API_PATH = "/v5/user/query-api"
BYBIT_WALLET_BALANCE_PATH = "/v5/account/wallet-balance"
BINANCE_API_RESTRICTIONS_PATH = "/sapi/v1/account/apiRestrictions"
BINANCE_ACCOUNT_PATH = "/fapi/v3/account"
BINANCE_POSITION_RISK_PATH = "/fapi/v3/positionRisk"
BINANCE_SYMBOL_CONFIG_PATH = "/fapi/v1/symbolConfig"

# CLAUDE.md rule 8: the most that may ever be rendered is the last four
# characters, so every redaction below masks to exactly this shape.
_SENSITIVE_FIELD_NAMES = frozenset({"apikey", "secret", "secretkey", "api_secret"})

ItemStatus = Literal["answered", "refused", "unknown"]

ITEM_LABELS = {
    "P1": "P1 Bybit withdraw shape",
    "P2": "P2 Bybit trade capability",
    "P3": "P3 Binance apiRestrictions",
    "P4": "P4 live reads (vault key)",
    "P5": "P5 binding / expiry",
}


@dataclass(frozen=True, slots=True)
class ItemVerdict:
    """One probe item's answer. ``code`` is the venue's own refusal code,
    never a guess, and is ``None`` outside the ``refused`` status."""

    status: ItemStatus
    detail: str
    code: str | None = None


# --- pure helpers (RED-tested; no venue I/O) --------------------------------


def _mask(value: str) -> str:
    """The most that may ever be rendered: the last 4 characters, prefixed so
    it reads as a redaction rather than a truncated real value."""
    return f"***{value[-4:]}" if len(value) >= 4 else "***"


def redact_permissions_payload(payload: Any, secrets: Sequence[str] = ()) -> Any:
    """Walks a decoded JSON payload (dict/list/scalar) and returns a copy with
    every known secret shape masked to its last 4 characters.

    Two independent rules, both applied everywhere in the structure:

    1. Any mapping value whose key is named ``apiKey``/``secret`` (case
       insensitive) is masked -- this is what catches Bybit's ``query-api``
       echoing the key it was signed with straight back in the body.
    2. Any string anywhere in the payload that is EQUAL to one of the live
       ``secrets`` (the key/secret this probe is actually running as) is
       masked too, independent of which field it turns up under -- a venue
       that echoes a credential under an unexpected field name is exactly
       the case a name-only rule would miss.
    """
    if isinstance(payload, Mapping):
        redacted: dict[Any, Any] = {}
        for key, value in payload.items():
            if (
                isinstance(key, str)
                and key.lower() in _SENSITIVE_FIELD_NAMES
                and isinstance(value, str)
                and value
            ):
                redacted[key] = _mask(value)
            else:
                redacted[key] = redact_permissions_payload(value, secrets)
        return redacted
    if isinstance(payload, list):
        return [redact_permissions_payload(item, secrets) for item in payload]
    if isinstance(payload, str) and payload and payload in secrets:
        return _mask(payload)
    return payload


def format_signing_line(api_key: str, source: str) -> str:
    """The pre-call announcement, pinned as a pure function so the 'last four
    only' rule (CLAUDE.md rule 8) is checkable without capturing stdout."""
    if len(api_key) < 4:
        raise ValueError("api_key too short to announce safely")
    return f"Signing as ***{api_key[-4:]}  (from the {source})"


def format_item_verdict(item: str, verdict: ItemVerdict) -> str:
    """Renders one item's verdict, distinguishing ANSWERED, REFUSED (with the
    venue's own code) and UNKNOWN -- never collapsed into a bare yes/no."""
    label = ITEM_LABELS.get(item, item)
    if verdict.status == "refused":
        return f"{label}: REFUSED ({verdict.code}) -- {verdict.detail}"
    if verdict.status == "unknown":
        return f"{label}: UNKNOWN -- {verdict.detail}"
    return f"{label}: ANSWERED -- {verdict.detail}"


def extract_bybit_withdraw_shape(result: Mapping[str, Any]) -> ItemVerdict:
    """P1: does ``permissions.Wallet`` list ``Withdraw``?"""
    permissions = result.get("permissions")
    if not isinstance(permissions, Mapping):
        return ItemVerdict("unknown", f"no permissions object in result; keys={sorted(result)}")
    wallet = permissions.get("Wallet")
    if not isinstance(wallet, list):
        return ItemVerdict("unknown", f"permissions.Wallet missing or not a list: {wallet!r}")
    can_withdraw = "Withdraw" in wallet
    return ItemVerdict(
        "answered",
        f"permissions.Wallet={wallet!r} -- {'CAN' if can_withdraw else 'cannot'} withdraw",
    )


def extract_bybit_trade_capability(result: Mapping[str, Any]) -> ItemVerdict:
    """P2: ``readOnly``, ``permissions.ContractTrade``,
    ``permissions.Derivatives`` -- which field(s) carry "can trade linear
    perpetuals" on this account."""
    permissions = result.get("permissions")
    if not isinstance(permissions, Mapping):
        return ItemVerdict("unknown", f"no permissions object in result; keys={sorted(result)}")
    return ItemVerdict(
        "answered",
        f"readOnly={result.get('readOnly')!r} "
        f"ContractTrade={permissions.get('ContractTrade')!r} "
        f"Derivatives={permissions.get('Derivatives')!r}",
    )


def extract_bybit_binding_expiry(result: Mapping[str, Any]) -> ItemVerdict:
    """P5 (Bybit half): ``ips``, ``expiredAt``, ``deadlineDay`` -- shown to
    the owner as Settings snapshot fields, never gating anything."""
    return ItemVerdict(
        "answered",
        f"ips={result.get('ips')!r} expiredAt={result.get('expiredAt')!r} "
        f"deadlineDay={result.get('deadlineDay')!r}",
    )


def extract_binance_restrictions(payload: Mapping[str, Any]) -> ItemVerdict:
    """P3: ``enableWithdrawals`` (8b), ``enableFutures`` (trade capability),
    plus the shown-only transfer/IP fields."""
    for required in ("enableWithdrawals", "enableFutures"):
        if required not in payload:
            return ItemVerdict("unknown", f"{required} missing from apiRestrictions body")
    return ItemVerdict(
        "answered",
        f"enableWithdrawals={payload.get('enableWithdrawals')!r} "
        f"enableFutures={payload.get('enableFutures')!r} "
        f"enableInternalTransfer={payload.get('enableInternalTransfer')!r} "
        f"permitsUniversalTransfer={payload.get('permitsUniversalTransfer')!r} "
        f"ipRestrict={payload.get('ipRestrict')!r}",
    )


def extract_binance_binding_expiry(payload: Mapping[str, Any]) -> ItemVerdict:
    """P5 (Binance half): ``ipRestrict``, ``tradingAuthorityExpirationTime``."""
    return ItemVerdict(
        "answered",
        f"ipRestrict={payload.get('ipRestrict')!r} "
        f"tradingAuthorityExpirationTime="
        f"{payload.get('tradingAuthorityExpirationTime')!r}",
    )


def describe_failure(exc: BaseException) -> str:
    """An exception as one printable line, every known secret shape removed
    -- the owner pastes this script's output into a chat, and a transport
    error that echoes a signed query string would carry the signature with
    it."""
    return redact(f"{type(exc).__name__}: {exc}")


# --- GET-only HTTP helper -----------------------------------------------------


class GetOnlyTransport(httpx.AsyncBaseTransport):
    """The one point where this script touches the network. Refuses any HTTP
    method other than GET structurally: the probe places nothing and changes
    no setting, and this turns that promise into a checked fact instead of a
    comment nobody re-reads."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise RuntimeError(
                f"check_key_permissions.py is GET-only; refused "
                f"{request.method} {request.url.path}"
            )
        return await self._inner.handle_async_request(request)


def get_only_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        transport=GetOnlyTransport(httpx.AsyncHTTPTransport()),
    )


# --- Bybit --------------------------------------------------------------------


def _bybit_envelope(response: httpx.Response) -> tuple[int | None, str, Mapping[str, Any]]:
    """(retCode, retMsg, result) -- Bybit answers a rejection with HTTP 200
    and a non-zero retCode, so the status line alone would read a refusal as
    an answer."""
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


async def _bybit_signed_get(
    http: httpx.AsyncClient, signer: BybitSigner, path: str, params: Mapping[str, str]
) -> httpx.Response:
    signed = signer.sign_get(path, params)
    return await http.get(signed.path_with_query, headers=dict(signed.headers))


async def _bybit_query_api(
    http: httpx.AsyncClient, signer: BybitSigner, secrets: Sequence[str]
) -> Mapping[str, Any] | ItemVerdict:
    """One call to ``GET /v5/user/query-api`` serves P1, P2 and P5's Bybit
    half; the raw redacted result is printed once and the parsed ``result``
    mapping handed to each item's own extractor."""
    response = await _bybit_signed_get(http, signer, BYBIT_QUERY_API_PATH, {})
    code, msg, result = _bybit_envelope(response)
    if code != 0:
        status: ItemStatus = "unknown" if code is None else "refused"
        return ItemVerdict(
            status, f"retCode={code} retMsg={msg!r}", code=None if code is None else str(code)
        )
    print(f"    raw result: {redact_permissions_payload(dict(result), secrets)!r}")
    return result


async def probe_bybit_withdraw_shape(result: Mapping[str, Any] | ItemVerdict) -> ItemVerdict:
    if isinstance(result, ItemVerdict):
        return result
    return extract_bybit_withdraw_shape(result)


async def probe_bybit_trade_capability(result: Mapping[str, Any] | ItemVerdict) -> ItemVerdict:
    if isinstance(result, ItemVerdict):
        return result
    return extract_bybit_trade_capability(result)


async def probe_binding_and_expiry_bybit(result: Mapping[str, Any] | ItemVerdict) -> ItemVerdict:
    if isinstance(result, ItemVerdict):
        return result
    return extract_bybit_binding_expiry(result)


async def probe_bybit_live_reads(http: httpx.AsyncClient, signer: BybitSigner) -> ItemVerdict:
    """P4 (Bybit half): ``wallet-balance UNIFIED``, the 8(a) read."""
    response = await _bybit_signed_get(
        http, signer, BYBIT_WALLET_BALANCE_PATH, {"accountType": "UNIFIED"}
    )
    code, msg, _ = _bybit_envelope(response)
    if code == 0:
        return ItemVerdict("answered", "retCode=0 -- wallet-balance UNIFIED succeeded")
    status: ItemStatus = "unknown" if code is None else "refused"
    return ItemVerdict(
        status, f"retCode={code} retMsg={msg!r}", code=None if code is None else str(code)
    )


# --- Binance --------------------------------------------------------------------


def _binance_error(response: httpx.Response) -> tuple[int, str] | None:
    """``None`` when the body is not an error envelope. Binance rejects
    through the status line too, but a 200 body carrying a negative ``code``
    is a rejection just the same."""
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int) and code < 0:
            return code, str(body.get("msg", ""))
    return None


async def _binance_signed_get(
    http: httpx.AsyncClient,
    signer: BinanceSigner,
    path: str,
    params: Mapping[str, str] | None = None,
) -> httpx.Response:
    signed = signer.sign_get(path, params)
    return await http.get(signed.path_with_query, headers=dict(signed.headers))


async def _binance_api_restrictions(
    http: httpx.AsyncClient, signer: BinanceSigner, secrets: Sequence[str]
) -> Mapping[str, Any] | ItemVerdict:
    """One call to ``GET /sapi/v1/account/apiRestrictions`` serves P3 and P5's
    Binance half."""
    response = await _binance_signed_get(http, signer, BINANCE_API_RESTRICTIONS_PATH)
    error = _binance_error(response)
    if response.status_code != 200 or error is not None:
        if error is not None:
            code, msg = error
            return ItemVerdict("refused", f"msg={msg!r}", code=str(code))
        return ItemVerdict(
            "refused",
            f"HTTP {response.status_code}: {response.text[:200]}",
            code=str(response.status_code),
        )
    body: Any = response.json()
    if not isinstance(body, dict):
        return ItemVerdict("unknown", "non-object apiRestrictions body")
    print(f"    raw result: {redact_permissions_payload(body, secrets)!r}")
    return body


async def probe_binance_restrictions(payload: Mapping[str, Any] | ItemVerdict) -> ItemVerdict:
    if isinstance(payload, ItemVerdict):
        return payload
    return extract_binance_restrictions(payload)


async def probe_binding_and_expiry_binance(
    payload: Mapping[str, Any] | ItemVerdict,
) -> ItemVerdict:
    if isinstance(payload, ItemVerdict):
        return payload
    return extract_binance_binding_expiry(payload)


async def probe_binance_live_reads(http: httpx.AsyncClient, signer: BinanceSigner) -> ItemVerdict:
    """P4 (Binance half), WITH THE VAULT KEY: ``account``, ``positionRisk``,
    ``symbolConfig`` -- every Binance read GET that moves off ``.env`` in
    PR 3 must succeed here first."""
    failures: list[str] = []
    for label, path, params in (
        ("account", BINANCE_ACCOUNT_PATH, None),
        ("positionRisk", BINANCE_POSITION_RISK_PATH, None),
        ("symbolConfig", BINANCE_SYMBOL_CONFIG_PATH, {"symbol": "BTCUSDT"}),
    ):
        response = await _binance_signed_get(http, signer, path, params)
        error = _binance_error(response)
        if response.status_code != 200 or error is not None:
            detail = f"msg={error[1]!r}" if error is not None else f"HTTP {response.status_code}"
            failures.append(f"{label}: {detail}")
    if failures:
        return ItemVerdict("refused", "; ".join(failures))
    return ItemVerdict(
        "answered", "account, positionRisk, symbolConfig all succeeded with the vault key"
    )


def _print_item(item: str, verdict: ItemVerdict, *, source: str) -> None:
    print(f"  {format_item_verdict(item, verdict)}")
    print(f"    key used: {source}")


def _print_missing(items: tuple[str, ...], exchange: str, source: str, exc: BaseException) -> None:
    """A missing key names its OWN item as UNKNOWN, one line per item --
    the owner needs to know exactly which item has no answer and why, not
    just that a venue call happened somewhere upstream."""
    missing = ItemVerdict("unknown", f"no {source} key for {exchange}: {describe_failure(exc)}")
    for item in items:
        _print_item(item, missing, source=f"{source} (missing)")


# --- entry point ---------------------------------------------------------------


async def _bybit_pass(
    settings: Settings, api_key: str, api_secret: str, clock: SystemClock,
    source: str, items: tuple[str, ...],
) -> None:
    print(f"  {format_signing_line(api_key, source)}")
    signer = BybitSigner(
        BybitCredentials(api_key=api_key, api_secret=api_secret),
        clock,
        recv_window_ms=settings.bybit_recv_window_ms,
    )
    async with get_only_client(settings.bybit_base_url, settings.bybit_timeout_seconds) as http:
        query_api = await _bybit_query_api(http, signer, [api_key, api_secret])
        if "P1" in items:
            _print_item("P1", await probe_bybit_withdraw_shape(query_api), source=source)
        if "P2" in items:
            _print_item("P2", await probe_bybit_trade_capability(query_api), source=source)
        if "P4" in items:
            _print_item("P4", await probe_bybit_live_reads(http, signer), source=source)
        if "P5" in items:
            _print_item("P5", await probe_binding_and_expiry_bybit(query_api), source=source)


async def _binance_pass(
    settings: Settings, api_key: str, api_secret: str, clock: SystemClock,
    source: str, items: tuple[str, ...],
) -> None:
    print(f"  {format_signing_line(api_key, source)}")
    signer = BinanceSigner(
        BinanceCredentials(api_key=api_key, api_secret=api_secret),
        clock,
        recv_window_ms=settings.binance_recv_window_ms,
    )
    async with get_only_client(
        settings.binance_futures_base_url, settings.binance_timeout_seconds
    ) as http:
        restrictions = await _binance_api_restrictions(http, signer, [api_key, api_secret])
        if "P3" in items:
            _print_item("P3", await probe_binance_restrictions(restrictions), source=source)
        if "P4" in items:
            _print_item("P4", await probe_binance_live_reads(http, signer), source=source)
        if "P5" in items:
            _print_item("P5", await probe_binding_and_expiry_binance(restrictions), source=source)


async def _run_bybit(settings: Settings) -> None:
    print(f"\n=== BYBIT ({BYBIT_EXCHANGE}) ===")
    clock = SystemClock()
    try:
        async with vault_credentials(settings, BYBIT_EXCHANGE) as vaulted:
            await _bybit_pass(
                settings, vaulted.api_key, vaulted.api_secret, clock, "vault",
                ("P1", "P2", "P4", "P5"),
            )
    except (CredentialNotFound, InvariantViolation) as exc:
        _print_missing(("P1", "P2", "P4", "P5"), BYBIT_EXCHANGE, "vault", exc)
    except Exception as exc:  # one venue's failure must not hide the other's items
        print(f"  FAILED before any per-item verdict: {describe_failure(exc)}")

    print("\n  -- .env key ***Swka, last use before PR 3 retires it --")
    try:
        env = bybit_env_credentials(settings)
        await _bybit_pass(
            settings, env.api_key, env.api_secret, clock, "environment (***Swka)", ("P2",)
        )
    except (CredentialNotFound, InvariantViolation) as exc:
        _print_missing(("P2",), BYBIT_EXCHANGE, "environment (***Swka)", exc)
    except Exception as exc:
        print(f"  UNKNOWN -- .env Bybit key unavailable: {describe_failure(exc)}")


async def _run_binance(settings: Settings) -> None:
    print(f"\n=== BINANCE ({BINANCE_EXCHANGE}) ===")
    clock = SystemClock()
    try:
        async with vault_credentials(settings, BINANCE_EXCHANGE) as vaulted:
            await _binance_pass(
                settings, vaulted.api_key, vaulted.api_secret, clock, "vault",
                ("P3", "P4", "P5"),
            )
    except (CredentialNotFound, InvariantViolation) as exc:
        _print_missing(("P3", "P4", "P5"), BINANCE_EXCHANGE, "vault", exc)
    except Exception as exc:
        print(f"  FAILED before any per-item verdict: {describe_failure(exc)}")

    print("\n  -- .env read key, last use before PR 3 retires it --")
    try:
        env = binance_env_credentials(settings)
        await _binance_pass(
            settings, env.api_key, env.api_secret, clock, "environment (read key)", ("P3",)
        )
    except (CredentialNotFound, InvariantViolation) as exc:
        _print_missing(("P3",), BINANCE_EXCHANGE, "environment (read key)", exc)
    except Exception as exc:
        print(f"  UNKNOWN -- .env Binance key unavailable: {describe_failure(exc)}")


async def _run(settings: Settings) -> int:
    print("Key permission probe -- GET-only, places nothing, changes no setting")
    await _run_bybit(settings)
    await _run_binance(settings)
    return 0


def main() -> int:
    settings = get_settings()
    return asyncio.run(_run(settings))


if __name__ == "__main__":
    # Same Windows console guard every probe in this directory carries.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
