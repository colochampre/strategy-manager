"""The API process must not log the signed URL of a key inspector's request (S2).

Binance signs in the QUERY STRING, and ``httpx`` logs every request at INFO with
the full URL. The worker silences those two loggers to WARNING; the API process
used to log nothing from an inspector because it ran none. From PR 8a-3 it
does, on the owner's own key, so the same setting must be applied at API
startup or the signature lands in the journal on every save.

The signature is timestamp-bound and the key travels in a header, so this is
noise rather than a live leak. It is still noise that carries a credential's
derivative, with no reason to exist.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.infrastructure.key_inspectors.binance import BinanceKeyInspector
from strategy_manager.main import create_app
from strategy_manager.shared.infrastructure.http_logging import silence_http_client_info_logs

# Sentinels, never a real credential (rule 1).
API_KEY = "S2-FAKE-KEY-abcd"
API_SECRET = "S2-FAKE-SECRET-wxyz"

_CLIENT_LOGGERS = ("httpx", "httpcore")


class _FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def capture() -> Iterator[_Capture]:
    """Every record at every level reaches ``capture``, with the two client
    loggers put back to 'inherit' first: a previous test may have silenced them,
    and this test is about what ``create_app()`` does."""
    handler = _Capture()
    root = logging.getLogger()
    saved_root_level = root.level
    saved = {name: logging.getLogger(name).level for name in _CLIENT_LOGGERS}
    for name in _CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(saved_root_level)
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


async def _signed_inspection() -> None:
    inspector = BinanceKeyInspector(
        base_url="https://fapi.test",
        timeout_seconds=5.0,
        recv_window_ms=5000,
        clock=_FrozenClock(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"assets": []})),
    )
    await inspector.inspect(
        ExchangeCredential(
            exchange="binance", label="default", api_key=API_KEY, api_secret=API_SECRET
        )
    )


async def test_a_signed_inspector_request_in_the_api_process_logs_no_query_string_or_signature(
    capture: _Capture,
) -> None:
    create_app()

    await _signed_inspection()

    said = [record.getMessage() for record in capture.records]
    assert [line for line in said if "signature" in line or "timestamp=" in line] == []
    assert [line for line in said if "fapi.test" in line] == []


async def test_without_the_setting_the_same_request_does_log_the_signature(
    capture: _Capture,
) -> None:
    """Proves the test above can fail: with the client loggers left alone, the
    very same request puts the signed URL into a record."""
    await _signed_inspection()

    said = " ".join(record.getMessage() for record in capture.records)
    assert "signature=" in said


def test_the_helper_sets_both_client_loggers_to_warning_and_is_idempotent(
    capture: _Capture,
) -> None:
    silence_http_client_info_logs()
    silence_http_client_info_logs()

    assert [logging.getLogger(name).level for name in _CLIENT_LOGGERS] == [
        logging.WARNING,
        logging.WARNING,
    ]
    assert logging.getLogger("strategy_manager").level == logging.NOTSET


def test_a_failing_request_is_still_allowed_through_at_warning(capture: _Capture) -> None:
    """WARNING rather than silence: whatever a client says about a FAILURE must
    still be heard."""
    silence_http_client_info_logs()

    logging.getLogger("httpx").warning("request failed")
    logging.getLogger("httpx").info("HTTP Request: GET https://x/?signature=abc")

    assert [record.getMessage() for record in capture.records] == ["request failed"]
