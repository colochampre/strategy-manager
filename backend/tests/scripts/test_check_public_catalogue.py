"""Unit tests for ``check_public_catalogue.py`` (probe P7, task 9v0.1).

No network and no credential: every request is answered by an
``httpx.MockTransport``. The script is GET-only and unsigned by construction,
and the first test pins that on the wire.
"""

import ast
import json
from pathlib import Path
from typing import Any

import check_public_catalogue as probe
import httpx
import pytest

BYBIT = "https://bybit.test"
BINANCE = "https://binance.test"


def _bybit_entry(
    symbol: str,
    contract_type: str = "LinearPerpetual",
    status: str = "Trading",
    settle: str = "USDT",
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "contractType": contract_type,
        "status": status,
        "settleCoin": settle,
    }


def _binance_entry(
    symbol: str,
    contract_type: str = "PERPETUAL",
    status: str = "TRADING",
    margin: str = "USDT",
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "contractType": contract_type,
        "status": status,
        "marginAsset": margin,
    }


# Seven Bybit entries: 3 survive the USDT filter (BTC, ETH, SFP).
BYBIT_ENTRIES = [
    _bybit_entry("BTCUSDT"),
    _bybit_entry("ETHUSDT"),
    _bybit_entry("SFPUSDT"),
    _bybit_entry("AAVEUSDT", status="Closed"),
    _bybit_entry("BTCUSDT-25DEC26", contract_type="LinearFutures"),
    _bybit_entry("BTCPERP", settle="USDC"),
    _bybit_entry("XRPUSDT", status="PreLaunch"),
]

BINANCE_ENTRIES = [
    _binance_entry("BTCUSDT"),
    _binance_entry("SFPUSDT"),
    _binance_entry("AAVEUSDT", status="BREAK"),
    _binance_entry("BTCUSDT_251226", contract_type="CURRENT_QUARTER"),
    _binance_entry("BTCUSDC", margin="USDC"),
]


class Recorder:
    """A mock transport that records every request it receives."""

    def __init__(self, bybit_page_size: int = 3, last_cursor: str | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._page_size = bybit_page_size
        # None -> the key is absent on the last page; "" -> present and empty.
        self._last_cursor = last_cursor
        self.binance_status = 200
        self.bybit_status = 200
        self.bybit_entries = BYBIT_ENTRIES
        self.bybit_overlap = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "bybit.test":
            return self._bybit(request)
        return self._binance()

    def _bybit(self, request: httpx.Request) -> httpx.Response:
        if self.bybit_status != 200:
            return httpx.Response(self.bybit_status, json={"retMsg": "refused"})
        offset = int(request.url.params.get("cursor") or 0)
        size = self._page_size
        start = max(offset - 1, 0) if self.bybit_overlap and offset else offset
        page = self.bybit_entries[start : offset + size]
        end = offset + size
        result: dict[str, Any] = {"category": "linear", "list": page}
        if end < len(self.bybit_entries):
            result["nextPageCursor"] = str(end)
        elif self._last_cursor is not None:
            result["nextPageCursor"] = self._last_cursor
        body = {"retCode": 0, "retMsg": "OK", "result": result}
        return httpx.Response(
            200,
            json=body,
            headers={"X-Bapi-Limit-Status": "599", "Set-Cookie": "secret=1"},
        )

    def _binance(self) -> httpx.Response:
        if self.binance_status != 200:
            return httpx.Response(self.binance_status, json={"code": 0, "msg": "restricted"})
        return httpx.Response(
            200,
            json={"symbols": BINANCE_ENTRIES},
            headers={"x-mbx-used-weight-1m": "10", "Server": "nginx"},
        )


def _index(reports: list[probe.VenueReport]) -> dict[str, probe.VenueReport]:
    by_venue = {report.venue: report for report in reports}
    assert set(by_venue) == {"bybit", "binance"}
    return by_venue


async def _run(recorder: Recorder) -> dict[str, probe.VenueReport]:
    return _index(
        await probe.run(
            bybit_base_url=BYBIT, binance_base_url=BINANCE, transport=recorder.transport()
        )
    )


async def test_no_request_carries_an_auth_header_or_a_signature_parameter() -> None:
    recorder = Recorder()
    await probe.run(
        bybit_base_url=BYBIT, binance_base_url=BINANCE, transport=recorder.transport()
    )

    assert recorder.requests, "the probe sent nothing"
    for request in recorder.requests:
        header_names = {name.lower() for name in request.headers}
        assert request.method == "GET"
        assert not {name for name in header_names if name.startswith("x-bapi")}
        assert "x-mbx-apikey" not in header_names
        assert "authorization" not in header_names
        params = {name.lower() for name in request.url.params}
        assert "signature" not in params
        assert "timestamp" not in params


async def test_report_counts_entries_by_contract_type_status_and_settle_coin() -> None:
    reports = await _run(Recorder())

    bybit = reports["bybit"]
    assert bybit.outcome == "ok"
    assert bybit.http_status == 200
    assert bybit.entries == 7
    assert bybit.by_contract_type == {"LinearPerpetual": 6, "LinearFutures": 1}
    assert bybit.by_status == {"Trading": 5, "Closed": 1, "PreLaunch": 1}
    assert bybit.by_settle_coin == {"USDT": 6, "USDC": 1}
    assert bybit.usdt_pairs == 3

    binance = reports["binance"]
    assert binance.outcome == "ok"
    assert binance.entries == 5
    assert binance.by_contract_type == {"PERPETUAL": 4, "CURRENT_QUARTER": 1}
    assert binance.by_status == {"TRADING": 4, "BREAK": 1}
    assert binance.by_settle_coin == {"USDT": 4, "USDC": 1}
    assert binance.usdt_pairs == 2
    assert binance.cursor_present is None


@pytest.mark.parametrize("last_cursor", [None, ""], ids=["absent", "empty"])
async def test_bybit_cursor_is_followed_and_every_entry_is_counted_once(
    last_cursor: str | None,
) -> None:
    recorder = Recorder(bybit_page_size=3, last_cursor=last_cursor)
    bybit = (await _run(recorder))["bybit"]

    assert bybit.entries == 7
    assert sum(bybit.by_contract_type.values()) == 7
    assert bybit.cursor_present is True
    assert bybit.last_page_cursor == ("absent" if last_cursor is None else "empty")
    assert bybit.pages_at_1000 == 3
    assert bybit.pages_at_200 == 3
    assert bybit.every_entry_once is True
    limits = {r.url.params["limit"] for r in recorder.requests if r.url.host == "bybit.test"}
    assert limits == {"1000", "200"}
    bybit_requests = [r for r in recorder.requests if r.url.host == "bybit.test"]
    assert all(r.url.params["category"] == "linear" for r in bybit_requests)


async def test_bybit_without_a_cursor_reports_it_absent() -> None:
    recorder = Recorder(bybit_page_size=100)
    bybit = (await _run(recorder))["bybit"]

    assert bybit.cursor_present is False
    assert bybit.pages_at_1000 == 1
    assert bybit.entries == 7


async def test_bybit_repeated_entries_across_pages_are_not_reported_as_once() -> None:
    recorder = Recorder(bybit_page_size=3)
    recorder.bybit_overlap = True
    bybit = (await _run(recorder))["bybit"]

    assert bybit.every_entry_once is False


async def test_report_says_whether_each_known_pair_is_available() -> None:
    reports = await _run(Recorder())

    expected = {"SFPUSDT": True, "AAVEUSDT": False, "STXUSDT": False}
    assert reports["bybit"].known_pairs == expected
    assert reports["binance"].known_pairs == expected


async def test_http_451_is_reported_as_a_location_refusal_not_as_an_empty_catalogue() -> None:
    recorder = Recorder()
    recorder.binance_status = 451
    reports = await _run(recorder)

    binance = reports["binance"]
    assert binance.outcome == "location_refused"
    assert binance.http_status == 451
    assert binance.entries == 0
    text = "\n".join(probe.render_report(list(reports.values())))
    assert "LOCATION REFUSED" in text
    # The other venue's result is not hidden by this failure.
    assert reports["bybit"].outcome == "ok"
    assert reports["bybit"].entries == 7


async def test_a_failing_venue_does_not_hide_the_other_and_is_named() -> None:
    recorder = Recorder()
    recorder.bybit_status = 500
    reports = await _run(recorder)

    assert reports["bybit"].outcome == "http_error"
    assert reports["bybit"].http_status == 500
    assert reports["binance"].outcome == "ok"
    text = "\n".join(probe.render_report(list(reports.values())))
    assert "HTTP ERROR" in text
    assert "http=500" in text


async def test_a_network_error_is_reported_per_venue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bybit.test":
            raise httpx.ConnectError("no route")
        return httpx.Response(200, json={"symbols": BINANCE_ENTRIES})

    by_venue = _index(
        await probe.run(
            bybit_base_url=BYBIT,
            binance_base_url=BINANCE,
            transport=httpx.MockTransport(handler),
        )
    )

    assert by_venue["bybit"].outcome == "failed"
    assert "ConnectError" in by_venue["bybit"].detail
    assert by_venue["binance"].outcome == "ok"


async def test_a_bybit_retcode_over_http_200_is_a_failure_not_an_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bybit.test":
            return httpx.Response(200, json={"retCode": 10001, "retMsg": "bad", "result": {}})
        return httpx.Response(200, json={"symbols": BINANCE_ENTRIES})

    by_venue = _index(
        await probe.run(
            bybit_base_url=BYBIT,
            binance_base_url=BINANCE,
            transport=httpx.MockTransport(handler),
        )
    )

    assert by_venue["bybit"].outcome == "failed"
    assert "10001" in by_venue["bybit"].detail
    assert by_venue["bybit"].entries == 0


async def test_only_rate_limit_headers_are_reported_and_nothing_else() -> None:
    reports = await _run(Recorder())

    assert reports["bybit"].rate_limit_headers == {"x-bapi-limit-status": "599"}
    assert reports["binance"].rate_limit_headers == {"x-mbx-used-weight-1m": "10"}
    text = json.dumps(probe.render_report(list(reports.values())))
    assert "secret=1" not in text
    assert "nginx" not in text


async def test_render_shows_the_filter_strings_the_design_relies_on() -> None:
    reports = await _run(Recorder())
    text = "\n".join(probe.render_report(list(reports.values())))

    for needle in ("LinearPerpetual", "Trading", "PERPETUAL", "TRADING", "SFPUSDT", "STXUSDT"):
        assert needle in text


def test_script_imports_no_signer_vault_or_cipher() -> None:
    source = Path(probe.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [alias.name for alias in node.names]

    forbidden = ("signer", "vault", "cipher", "probe_credentials", "credential", "transport")
    offenders = [name for name in imported if any(word in name.lower() for word in forbidden)]
    assert offenders == []
    assert not [n for n in imported if n.startswith("strategy_manager.") and "infrastructure" in n]
