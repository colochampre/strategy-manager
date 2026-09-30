"""No log record, at any level, may carry the key or the secret of a real PUT.

``PUT /api/credentials/{exchange}`` carries an API key and its secret in the
BODY. Nothing in this system is meant to log a body, but "meant to" is what the
webhook-secret work (PR 7b) learned not to rely on, so this drives one REAL
uvicorn server, with uvicorn's own logging configuration and access log, over a
real socket, and looks at every record every logger produced:

- ``uvicorn.access`` and ``uvicorn.error`` (the request line, and the traceback
  if anything had crashed);
- the application loggers (``strategy_manager.*``, including ``SaveCredential``'s
  own lines);
- ``httpx`` and ``httpcore``, which log the signed URL of the inspector's request
  at INFO unless the API process silences them (S2). The inspector below is the
  REAL Binance inspector over a mock transport, so that request is made.

Rule 1: the key and secret are sentinels, the venue is a ``MockTransport``.
"""

import asyncio
import logging
from typing import Any

import httpx
import pytest
import uvicorn
from httpx import AsyncClient

from strategy_manager.accounts.application.save_credential import SaveCredential
from strategy_manager.accounts.infrastructure.credentials_router import get_save_credential
from strategy_manager.accounts.infrastructure.key_inspectors.binance import BinanceKeyInspector
from strategy_manager.accounts.infrastructure.key_inspectors.registry import KeyInspectorRegistry
from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings
from tests.accounts.fakes import (
    NOW,
    RecordingCommit,
    RecordingPoolWriter,
    RecordingWriter,
    TickingClock,
)
from tests.signals.infrastructure.test_webhook_secret_router import (
    _all_loggers,
    _Capture,
    _everything_a_record_says,
    _logging_restored,
)

TOKEN = "adm1n-t0ken"
KEY = "LOGTEST-FAKE-KEY-0a1b2c"
SECRET = "LOGTEST-FAKE-SECRET-3d4e5f-must-never-leak"


class _FrozenClock:
    def now(self) -> Any:
        return NOW


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


async def test_no_log_record_at_any_level_carries_the_key_or_the_secret_on_a_real_put(
    capsys: pytest.CaptureFixture[str],
) -> None:
    venue_requests: list[httpx.Request] = []

    def venue(request: httpx.Request) -> httpx.Response:
        venue_requests.append(request)
        return httpx.Response(200, json={"assets": []})

    inspector = BinanceKeyInspector(
        base_url="https://fapi.test",
        timeout_seconds=5.0,
        recv_window_ms=5000,
        clock=_FrozenClock(),
        transport=httpx.MockTransport(venue),
    )
    writer = RecordingWriter()
    commit = RecordingCommit()
    capture = _Capture()

    with _logging_restored():
        app = create_app()
        use_case = SaveCredential(
            KeyInspectorRegistry({"binance": inspector}),
            writer,
            RecordingPoolWriter(),
            commit,
            TickingClock(),
        )
        app.dependency_overrides[get_save_credential] = lambda: use_case

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_level="debug",
            access_log=True,
        )
        # Hook every logger that exists once uvicorn has configured logging, and
        # the root, whose level is opened so nothing is dropped for being quiet.
        logging.root.setLevel(logging.DEBUG)
        logging.root.addHandler(capture)
        for lg in _all_loggers():
            lg.addHandler(capture)

        server = uvicorn.Server(config)
        serving = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started, "the uvicorn server did not start"
            port = server.servers[0].sockets[0].getsockname()[1]

            headers = {"Authorization": f"Bearer {TOKEN}"}
            async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as api:
                saved = await api.put(
                    "/api/credentials/binance",
                    json={
                        "api_key": KEY,
                        "api_secret": SECRET,
                        "withdrawals_disabled_confirmed": True,
                        "futures_enabled_confirmed": True,
                    },
                    headers=headers,
                )
                refused = await api.put(
                    "/api/credentials/binance",
                    json={"api_key": KEY, "api_secret": {"nested": SECRET}},
                    headers=headers,
                )
        finally:
            server.should_exit = True
            await serving

    # The request really ran through the real path: the venue was asked once
    # with a signed URL, the credential was stored, and the second body was refused.
    assert saved.status_code == 200
    assert saved.json()["last4"] == KEY[-4:]
    assert len(venue_requests) == 1
    assert "signature=" in str(venue_requests[0].url)
    assert [credential.api_key for credential, _ in writer.stored] == [KEY]
    assert refused.status_code == 422
    for response in (saved, refused):
        assert KEY not in response.text
        assert SECRET not in response.text

    records = list(capture.records.values())
    access_lines = [
        r.getMessage()
        for r in records
        if r.name == "uvicorn.access" and "/api/credentials/binance" in r.getMessage()
    ]
    assert len(access_lines) == 2, "both PUTs must reach the access log, or nothing was proven"

    said = {id(r): _everything_a_record_says(r) for r in records}
    sources = sorted({r.name for r in records})
    assert "uvicorn.access" in sources
    assert any(name.startswith("strategy_manager") for name in sources), (
        "SaveCredential's own INFO line must be among the records inspected"
    )

    leaked_key = [r.name for r in records if KEY in said[id(r)]]
    leaked_secret = [r.name for r in records if SECRET in said[id(r)]]
    signed_url = [r.name for r in records if "signature=" in said[id(r)]]
    assert leaked_key == [], f"the key reached log records from: {leaked_key}"
    assert leaked_secret == [], f"the secret reached log records from: {leaked_secret}"
    assert signed_url == [], f"a signed venue URL reached log records from: {signed_url}"
    assert [r.name for r in records if r.name in {"httpx", "httpcore"}] == []

    streams = capsys.readouterr()
    for stream in (streams.out, streams.err):
        assert KEY not in stream
        assert SECRET not in stream
        assert "signature=" not in stream
