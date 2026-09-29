"""RED-first tests for ``probe_binance_futures_permission.py`` (task 8a.0a).

Every request goes through ``httpx.MockTransport`` with FAKE keys: no real
credential and no network (CLAUDE.md rule 1). The properties pinned here are
the ones that make the owner-run probe safe to paste into a chat: GET-only, a
fixed path allowlist, and no secret, signature, query string or payload beyond
the documented fields ever reaching stdout or stderr.
"""

from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from probe_binance_futures_permission import (
    ALLOWED_PATHS,
    KeySpec,
    load_probe_specs,
    run_probe,
)

VAULT_KEY = "VAULTAPIKEYFAKE0000abcd"
VAULT_SECRET = "VAULTSECRETFAKE1111efgh"
TEMP_KEY = "TEMPAPIKEYFAKE2222wxyz"
TEMP_SECRET = "TEMPSECRETFAKE3333ijkl"

FAKE_WALLET = "48211.90731122"
FAKE_UID = 918273645
FAKE_SYMBOL = "ZZFAKEUSDT"

EXPECTED_PATHS = {
    "/fapi/v3/account",
    "/fapi/v2/account",
    "/fapi/v3/balance",
    "/fapi/v3/positionRisk",
    "/fapi/v1/apiTradingStatus",
    "/fapi/v1/account/permissions",
}


def _account_payload(can_trade: bool) -> dict[str, object]:
    return {
        "canTrade": can_trade,
        "canDeposit": True,
        "canWithdraw": False,
        "totalWalletBalance": FAKE_WALLET,
        "uid": FAKE_UID,
        "assets": [{"asset": "USDT", "walletBalance": FAKE_WALLET}],
        "positions": [{"symbol": FAKE_SYMBOL, "positionAmt": "3.5"}],
    }


class Recorder:
    """A fake Binance. The vault key reads everything with canTrade=True; the
    temporary key is refused with -2015 unless ``temp_reads_ok``."""

    def __init__(self, *, temp_reads_ok: bool = False, temp_can_trade: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self._temp_reads_ok = temp_reads_ok
        self._temp_can_trade = temp_can_trade

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.headers["X-MBX-APIKEY"]
        path = request.url.path
        if key == TEMP_KEY and not self._temp_reads_ok:
            return httpx.Response(
                401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action"}
            )
        can_trade = True if key == VAULT_KEY else self._temp_can_trade
        if path in ("/fapi/v3/account", "/fapi/v2/account"):
            return httpx.Response(200, json=_account_payload(can_trade))
        if path == "/fapi/v3/balance":
            return httpx.Response(
                200, json=[{"asset": "USDT", "balance": FAKE_WALLET}, {"asset": "BNB"}]
            )
        if path == "/fapi/v3/positionRisk":
            return httpx.Response(
                200, json=[{"symbol": FAKE_SYMBOL, "entryPrice": "123.4567"}] * 3
            )
        if path == "/fapi/v1/apiTradingStatus":
            return httpx.Response(
                200, json={"indicators": {}, "updateTime": 1, "isLocked": False}
            )
        return httpx.Response(404, json={"code": -5000, "msg": "Path not found"})


def _specs(*, with_temp: bool = True) -> list[KeySpec]:
    specs = [KeySpec("vault", VAULT_KEY, VAULT_SECRET)]
    if with_temp:
        specs.append(KeySpec("temporary read-only", TEMP_KEY, TEMP_SECRET))
    return specs


async def _run(recorder: Recorder, specs: list[KeySpec]) -> int:
    return await run_probe(specs, transport=httpx.MockTransport(recorder))


async def test_every_request_is_a_get_on_an_allowlisted_path() -> None:
    recorder = Recorder()

    await _run(recorder, _specs())

    assert recorder.requests, "the probe sent nothing"
    assert {r.method for r in recorder.requests} == {"GET"}
    assert {r.url.path for r in recorder.requests} == EXPECTED_PATHS
    assert set(ALLOWED_PATHS) == EXPECTED_PATHS
    # Each key calls each path once.
    assert len(recorder.requests) == 2 * len(EXPECTED_PATHS)
    assert {r.url.host for r in recorder.requests} == {"fapi.binance.com"}


async def test_requests_carry_timestamp_recvwindow_and_a_signature() -> None:
    recorder = Recorder()

    await _run(recorder, _specs(with_temp=False))

    assert recorder.requests, "the probe sent nothing"
    query = parse_qs(urlsplit(str(recorder.requests[0].url)).query)
    assert query["recvWindow"] == ["5000"]
    assert "timestamp" in query and "signature" in query


async def test_output_never_contains_keys_secrets_signatures_or_queries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorder = Recorder()

    await _run(recorder, _specs())

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert recorder.requests, "the probe sent nothing"
    for forbidden in (VAULT_KEY, VAULT_SECRET, TEMP_KEY, TEMP_SECRET):
        assert forbidden not in out
    for request in recorder.requests:
        signature = parse_qs(urlsplit(str(request.url)).query)["signature"][0]
        assert signature not in out
    for fragment in ("signature", "timestamp=", "recvWindow", "?"):
        assert fragment not in out
    # The last four characters ARE the identification.
    assert "***abcd" in out
    assert "***wxyz" in out


async def test_output_states_which_key_each_line_belongs_to(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(), _specs())

    out = capsys.readouterr().out
    assert "vault key ***abcd" in out
    assert "temporary read-only key ***wxyz" in out


async def test_payload_extras_never_reach_the_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(temp_reads_ok=True), _specs())

    out = capsys.readouterr().out
    for leaked in (
        FAKE_WALLET,
        str(FAKE_UID),
        FAKE_SYMBOL,
        "totalWalletBalance",
        "assets",
        "positions",
        "123.4567",
        "walletBalance",
    ):
        assert leaked not in out
    assert "canTrade=True" in out
    assert "canDeposit=True" in out
    assert "canWithdraw=False" in out


async def test_balance_and_position_risk_print_only_an_entry_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(), _specs(with_temp=False))

    out = capsys.readouterr().out
    assert "/fapi/v3/balance" in out and "entries=2" in out
    assert "/fapi/v3/positionRisk" in out and "entries=3" in out


async def test_api_trading_status_prints_top_level_keys_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(), _specs(with_temp=False))

    out = capsys.readouterr().out
    assert "keys=['indicators', 'isLocked', 'updateTime']" in out
    assert "isLocked=False" not in out


async def test_a_2015_refusal_is_reported_with_its_code_and_msg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(), _specs())

    out = capsys.readouterr().out
    temp_lines = [line for line in out.splitlines() if "temporary read-only key ***wxyz" in line]
    assert temp_lines
    assert any(
        "401" in line and "-2015" in line and "Invalid API-key, IP, or permissions" in line
        for line in temp_lines
    )


async def test_missing_env_vars_run_the_vault_key_alone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    specs = load_probe_specs(VAULT_KEY, VAULT_SECRET, env={})
    recorder = Recorder()

    exit_code = await _run(recorder, specs)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert [s.kind for s in specs] == ["vault"]
    assert recorder.requests, "the probe sent nothing"
    assert {r.headers["X-MBX-APIKEY"] for r in recorder.requests} == {VAULT_KEY}
    assert "no temporary key" in out.lower()


async def test_missing_env_vars_are_named_in_the_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    load_probe_specs(VAULT_KEY, VAULT_SECRET, env={})

    assert "BINANCE_PROBE_API_KEY" in capsys.readouterr().out


async def test_env_vars_add_the_temporary_key() -> None:
    env = {"BINANCE_PROBE_API_KEY": TEMP_KEY, "BINANCE_PROBE_API_SECRET": TEMP_SECRET}

    specs = load_probe_specs(VAULT_KEY, VAULT_SECRET, env=env)

    assert [(s.kind, s.api_key) for s in specs] == [
        ("vault", VAULT_KEY),
        ("temporary read-only", TEMP_KEY),
    ]


async def test_only_one_of_the_two_env_vars_counts_as_missing() -> None:
    specs = load_probe_specs(VAULT_KEY, VAULT_SECRET, env={"BINANCE_PROBE_API_KEY": TEMP_KEY})

    assert [s.kind for s in specs] == ["vault"]


async def test_summary_says_a_key_without_enable_futures_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(), _specs())

    lines = capsys.readouterr().out.splitlines()
    assert "vault ***abcd: reads OK, canTrade=True" in lines
    assert "read-only ***wxyz: reads refused -2015" in lines
    verdict = [line for line in lines if line.startswith("VERDICT")]
    assert len(verdict) == 1
    assert "refused" in verdict[0]


async def test_summary_says_when_can_trade_differed_between_the_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(temp_reads_ok=True, temp_can_trade=False), _specs())

    lines = capsys.readouterr().out.splitlines()
    assert "read-only ***wxyz: reads OK, canTrade=False" in lines
    verdict = next(line for line in lines if line.startswith("VERDICT"))
    assert "NOT refused" in verdict
    assert "canTrade differed" in verdict


async def test_summary_says_when_can_trade_did_not_differ(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _run(Recorder(temp_reads_ok=True, temp_can_trade=True), _specs())

    verdict = next(
        line for line in capsys.readouterr().out.splitlines() if line.startswith("VERDICT")
    )
    assert "canTrade did NOT differ" in verdict


async def test_transport_error_prints_class_and_message_without_the_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom while calling {request.url}", request=request)

    exit_code = await run_probe(_specs(with_temp=False), transport=httpx.MockTransport(handler))

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert exit_code == 0
    assert "ConnectError" in out
    for fragment in ("signature", "fapi.binance.com", "timestamp", "://", VAULT_KEY):
        assert fragment not in out


async def test_a_non_get_or_unlisted_path_cannot_be_sent() -> None:
    import probe_binance_futures_permission as module

    helper: Any = module._get  # type: ignore[attr-defined]
    recorder = Recorder()
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http:
        with pytest.raises(ValueError, match="allowlist"):
            await helper(http, object(), "/fapi/v1/order")
    assert recorder.requests == []
    assert not hasattr(module, "_post")
