"""The venue key inspectors -- rule 8a's live read plus the facts a venue can prove.

Every request goes through ``httpx.MockTransport``, which records each method
and path, so "GET-only, never an order, never SAPI" is a checked fact and not a
comment. Rule 1: no real credential; the keys below are made up.

Payload shapes come from what ``scripts/check_key_permissions.py`` documents
and the probes recorded (tasks.md, "PR 1 -- Probe results" and probe P6), never
from a real payload.
"""

import ast
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from strategy_manager.accounts.domain.errors import KeyRejected, VenueUnreachable
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot, UnservedExchange
from strategy_manager.accounts.infrastructure.key_inspectors import binance as binance_module
from strategy_manager.accounts.infrastructure.key_inspectors import bybit as bybit_module
from strategy_manager.accounts.infrastructure.key_inspectors.binance import BinanceKeyInspector
from strategy_manager.accounts.infrastructure.key_inspectors.bybit import BybitKeyInspector
from strategy_manager.accounts.infrastructure.key_inspectors.registry import KeyInspectorRegistry

API_KEY = "FAKE-INSPECTOR-KEY-abcd"
API_SECRET = "FAKE-INSPECTOR-SECRET-wxyz"
WHITELISTED_IP = "203.0.113.7"


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


class Recorder:
    """A MockTransport handler that remembers every request it saw."""

    def __init__(self, answer: Callable[[httpx.Request], httpx.Response]) -> None:
        self._answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._answer(request)

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def _credential(exchange: str) -> ExchangeCredential:
    return ExchangeCredential(
        exchange=exchange, label="default", api_key=API_KEY, api_secret=API_SECRET
    )


# --- Bybit -----------------------------------------------------------------

# P4: wallet-balance UNIFIED, reduced to the envelope the read client unwraps.
BYBIT_WALLET_BALANCE: dict[str, Any] = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {"list": [{"accountType": "UNIFIED", "coin": []}]},
}


def _bybit_key_info(
    *, read_only: object = 0, wallet: object = ("AccountTransfer", "SubMemberTransfer")
) -> dict[str, Any]:
    """P1/P2 shape. The lists other than ``Wallet`` are present on purpose: a
    read-only key still lists ``ContractTrade`` and ``Derivatives``."""
    permissions: dict[str, Any] = {
        "ContractTrade": ["Order", "Position"],
        "Derivatives": ["DerivativesTrade"],
    }
    if wallet is not None:
        permissions["Wallet"] = list(wallet) if isinstance(wallet, tuple) else wallet
    result: dict[str, Any] = {
        "id": "1",
        "apiKey": API_KEY,
        "permissions": permissions,
        "ips": [WHITELISTED_IP],
        "expiredAt": "1970-01-01T00:00:00Z",
        "deadlineDay": -2,
    }
    if read_only is not None:
        result["readOnly"] = read_only
    return {"retCode": 0, "retMsg": "OK", "result": result}


def _bybit_answer(
    key_info: dict[str, Any] | None = None, balance: dict[str, Any] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v5/account/wallet-balance":
            return httpx.Response(200, json=balance or BYBIT_WALLET_BALANCE)
        if request.url.path == "/v5/user/query-api":
            return httpx.Response(200, json=key_info or _bybit_key_info())
        return httpx.Response(404, json={"retCode": 404, "retMsg": "unexpected path"})

    return answer


def _bybit(recorder: Recorder) -> BybitKeyInspector:
    return BybitKeyInspector(
        base_url="https://bybit.test",
        timeout_seconds=5.0,
        recv_window_ms=5000,
        clock=FrozenClock(),
        transport=httpx.MockTransport(recorder),
    )


async def test_bybit_inspector_calls_wallet_balance_and_query_api_never_an_order() -> None:
    recorder = Recorder(_bybit_answer())

    snapshot = await _bybit(recorder).inspect(_credential("bybit"))

    assert recorder.paths == ["/v5/account/wallet-balance", "/v5/user/query-api"]
    assert recorder.methods == ["GET", "GET"]
    assert recorder.requests[0].url.params["accountType"] == "UNIFIED"
    assert snapshot == PermissionSnapshot(
        wallet_permissions=frozenset({"AccountTransfer", "SubMemberTransfer"}),
        read_only=False,
    )


async def test_bybit_inspector_read_only_one_maps_to_true_regardless_of_the_permission_lists() -> (
    None
):
    recorder = Recorder(_bybit_answer(_bybit_key_info(read_only=1)))

    snapshot = await _bybit(recorder).inspect(_credential("bybit"))

    assert snapshot.read_only is True


@pytest.mark.parametrize(
    "wallet", [None, "Withdraw", {"AccountTransfer": True}, ["AccountTransfer", 7]]
)
async def test_bybit_inspector_missing_or_non_list_wallet_is_none_and_warns_once_naming_the_exchange(  # noqa: E501
    wallet: object, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = Recorder(_bybit_answer(_bybit_key_info(wallet=wallet)))

    with caplog.at_level(logging.WARNING):
        snapshot = await _bybit(recorder).inspect(_credential("bybit"))

    assert snapshot.wallet_permissions is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "bybit" in message
    for leaked in (API_KEY, API_SECRET, WHITELISTED_IP, "AccountTransfer"):
        assert leaked not in message


@pytest.mark.parametrize("read_only", [None, "0", 2, True, "true"])
async def test_bybit_inspector_missing_or_unrecognised_read_only_is_none_and_warns_once(
    read_only: object, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = Recorder(_bybit_answer(_bybit_key_info(read_only=read_only)))

    with caplog.at_level(logging.WARNING):
        snapshot = await _bybit(recorder).inspect(_credential("bybit"))

    assert snapshot.read_only is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "bybit" in warnings[0].getMessage()
    assert WHITELISTED_IP not in warnings[0].getMessage()


async def test_bybit_inspector_a_complete_answer_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = Recorder(_bybit_answer())

    with caplog.at_level(logging.WARNING):
        await _bybit(recorder).inspect(_credential("bybit"))

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.parametrize("code", [10003, 10004, 33004])
@pytest.mark.parametrize("failing_path", ["/v5/account/wallet-balance", "/v5/user/query-api"])
async def test_bybit_inspector_maps_auth_codes_to_key_rejected_on_either_call(
    code: int, failing_path: str
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == failing_path:
            return httpx.Response(200, json={"retCode": code, "retMsg": "nope", "result": {}})
        return _bybit_answer()(request)

    recorder = Recorder(answer)

    with pytest.raises(KeyRejected) as raised:
        await _bybit(recorder).inspect(_credential("bybit"))

    assert str(code) in str(raised.value)
    assert API_KEY not in str(raised.value)
    assert API_SECRET not in str(raised.value)


async def test_bybit_inspector_maps_5xx_and_transport_failures_to_venue_unreachable() -> None:
    down = Recorder(lambda _r: httpx.Response(503, text="upstream down"))
    with pytest.raises(VenueUnreachable):
        await _bybit(down).inspect(_credential("bybit"))

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(VenueUnreachable):
        await _bybit(Recorder(refuse)).inspect(_credential("bybit"))


# --- Binance ---------------------------------------------------------------

# Probe P6's `/fapi/v2/account` payload: the ACCOUNT-level flags were True on a
# key that could neither trade futures nor withdraw. Fed to the inspector to
# prove it does not read them.
P6_V2_ACCOUNT: dict[str, Any] = {
    "canTrade": True,
    "canDeposit": True,
    "canWithdraw": True,
    "feeTier": 0,
    "totalWalletBalance": "0.00000000",
    "assets": [],
    "positions": [],
}


def _binance(recorder: Recorder) -> BinanceKeyInspector:
    return BinanceKeyInspector(
        base_url="https://fapi.test",
        timeout_seconds=5.0,
        recv_window_ms=5000,
        clock=FrozenClock(),
        transport=httpx.MockTransport(recorder),
    )


async def test_binance_inspector_calls_fapi_v3_account_only_never_sapi_never_an_order() -> None:
    recorder = Recorder(lambda _r: httpx.Response(200, json={"assets": []}))

    snapshot = await _binance(recorder).inspect(_credential("binance"))

    assert recorder.paths == ["/fapi/v3/account"]
    assert recorder.methods == ["GET"]
    assert snapshot == PermissionSnapshot()


async def test_binance_inspector_ignores_can_trade_and_can_withdraw_p6_fixture_snapshot_stays_empty() -> (  # noqa: E501
    None
):
    recorder = Recorder(lambda _r: httpx.Response(200, json=P6_V2_ACCOUNT))

    snapshot = await _binance(recorder).inspect(_credential("binance"))

    assert snapshot.wallet_permissions is None
    assert snapshot.read_only is None
    assert snapshot == PermissionSnapshot()


@pytest.mark.parametrize("code", [-2014, -2015, -1022])
async def test_binance_inspector_maps_2014_2015_1022_to_key_rejected(code: int) -> None:
    body = {"code": code, "msg": "Invalid API-key, IP, or permissions for action."}
    recorder = Recorder(lambda _r: httpx.Response(401, json=body))

    with pytest.raises(KeyRejected) as raised:
        await _binance(recorder).inspect(_credential("binance"))

    assert str(code) in str(raised.value)
    assert API_KEY not in str(raised.value)


async def test_binance_inspector_2015_detail_says_it_also_covers_a_wrong_ip_or_permission() -> None:
    body = {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}
    recorder = Recorder(lambda _r: httpx.Response(401, json=body))

    with pytest.raises(KeyRejected) as raised:
        await _binance(recorder).inspect(_credential("binance"))

    message = str(raised.value).lower()
    assert "ip" in message
    assert "permission" in message


async def test_binance_inspector_maps_5xx_451_and_transport_failures_to_venue_unreachable() -> None:
    for status in (500, 503, 451):
        recorder = Recorder(lambda _r, s=status: httpx.Response(s, text="upstream"))
        with pytest.raises(VenueUnreachable):
            await _binance(recorder).inspect(_credential("binance"))

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(VenueUnreachable):
        await _binance(Recorder(refuse)).inspect(_credential("binance"))


async def test_binance_inspector_a_non_object_body_is_venue_unreachable_not_a_pass() -> None:
    recorder = Recorder(lambda _r: httpx.Response(200, content=json.dumps([1, 2, 3])))

    with pytest.raises(VenueUnreachable):
        await _binance(recorder).inspect(_credential("binance"))


# --- structure and registry -------------------------------------------------


@pytest.mark.parametrize("module", [bybit_module, binance_module])
def test_inspector_modules_cannot_reach_a_writing_client(module: Any) -> None:
    """Structural: no trade client import, no POST in the source."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("trade_client" in name for name in imported)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {"post", "put", "delete", "patch", "sign_post"}


def test_registry_dispatches_by_exchange_unserved_raises() -> None:
    recorder = Recorder(lambda _r: httpx.Response(200, json={}))
    bybit, binance = _bybit(recorder), _binance(recorder)
    registry = KeyInspectorRegistry({"bybit": bybit, "binance": binance})

    assert registry.for_exchange("bybit") is bybit
    assert registry.for_exchange("binance") is binance
    with pytest.raises(UnservedExchange, match="pionex"):
        registry.for_exchange("pionex")
