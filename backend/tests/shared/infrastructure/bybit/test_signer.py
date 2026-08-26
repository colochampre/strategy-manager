"""Bybit V5 signing.

The signature is computed over one byte sequence and transmitted alongside
another. Every test here pins the two together, because when they drift the
error says nothing useful -- it just says authentication failed.
"""

import hmac
from hashlib import sha256

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.bybit.signer import (
    KEY_HEADER,
    RECV_WINDOW_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    BybitCredentials,
    BybitSigner,
)
from tests.shared.infrastructure.bybit.conftest import (
    API_KEY,
    RECV_WINDOW,
    FrozenClock,
)


def _expected(secret: str, timestamp: int, payload: str) -> str:
    message = f"{timestamp}{API_KEY}{RECV_WINDOW}{payload}"
    return hmac.new(secret.encode(), message.encode(), sha256).hexdigest()


def test_a_get_signs_timestamp_key_window_and_query_in_that_order(
    signer: BybitSigner, api_secret: str, timestamp_ms: int
) -> None:
    """Bybit's documented string is timestamp + api_key + recv_window +
    queryString. Any other order authenticates against nothing."""
    signed = signer.sign_get("/v5/position/list", {"category": "linear"})

    assert signed.headers[SIGNATURE_HEADER] == _expected(
        api_secret, timestamp_ms, "category=linear"
    )


def test_a_post_signs_the_body_rather_than_a_query(
    signer: BybitSigner, api_secret: str, timestamp_ms: int
) -> None:
    body = '{"category":"linear","symbol":"BTCUSDT"}'

    signed = signer.sign_post("/v5/order/create", body)

    assert signed.headers[SIGNATURE_HEADER] == _expected(
        api_secret, timestamp_ms, body
    )
    assert signed.body == body


def test_the_transmitted_query_is_the_one_that_was_signed(
    signer: BybitSigner, api_secret: str, timestamp_ms: int
) -> None:
    """If the query is rebuilt from a mapping after signing, its order or
    encoding can change and the signature stops matching what was sent."""
    signed = signer.sign_get(
        "/v5/position/list", {"category": "linear", "settleCoin": "USDT"}
    )

    _, _, query = signed.path_with_query.partition("?")
    assert signed.headers[SIGNATURE_HEADER] == _expected(
        api_secret, timestamp_ms, query
    )


def test_parameter_order_is_preserved_and_never_sorted(
    signer: BybitSigner
) -> None:
    """Bybit signs the query as written. Sorting it behind the caller's back
    would produce a different string from the one the caller intended, and
    the only symptom would be an authentication failure."""
    signed = signer.sign_get(
        "/v5/market/tickers", {"symbol": "BTCUSDT", "category": "linear"}
    )

    assert signed.path_with_query.endswith("?symbol=BTCUSDT&category=linear")


def test_a_get_with_no_parameters_sends_no_question_mark(
    signer: BybitSigner, api_secret: str, timestamp_ms: int
) -> None:
    signed = signer.sign_get("/v5/account/info")

    assert signed.path_with_query == "/v5/account/info"
    assert signed.headers[SIGNATURE_HEADER] == _expected(api_secret, timestamp_ms, "")


def test_every_required_header_is_present(signer: BybitSigner) -> None:
    signed = signer.sign_get("/v5/account/info")

    assert signed.headers[KEY_HEADER] == API_KEY
    assert signed.headers[RECV_WINDOW_HEADER] == str(RECV_WINDOW)
    assert signed.headers[TIMESTAMP_HEADER].isdigit()
    assert len(signed.headers[SIGNATURE_HEADER]) == 64


def test_the_timestamp_header_matches_the_one_that_was_signed(
    signer: BybitSigner, api_secret: str
) -> None:
    """A signature signed with one timestamp and sent with another is
    rejected. Holding the timestamp as mutable state on the signer would make
    that failure depend on call order."""
    signed = signer.sign_get("/v5/account/info")

    sent = int(signed.headers[TIMESTAMP_HEADER])
    assert signed.headers[SIGNATURE_HEADER] == _expected(api_secret, sent, "")


def test_the_timestamp_comes_from_the_injected_clock(
    credentials: BybitCredentials, timestamp_ms: int
) -> None:
    """Bybit requires the timestamp to sit inside recv_window of its own
    clock, so this reads the port rather than the wall clock."""
    signer = BybitSigner(credentials, FrozenClock(), recv_window_ms=RECV_WINDOW)

    signed = signer.sign_get("/v5/account/info")

    assert signed.headers[TIMESTAMP_HEADER] == str(timestamp_ms)


def test_credentials_never_render_the_secret() -> None:
    """A default dataclass repr puts the secret into every log line and
    traceback that touches the object (CLAUDE.md rule 8)."""
    rendered = repr(BybitCredentials(api_key="abcdefgh", api_secret="super-secret"))

    assert "super-secret" not in rendered
    assert "***efgh" in rendered


@pytest.mark.parametrize(("key", "secret"), [("", "s"), ("k", "")])
def test_empty_credentials_are_refused_up_front(key: str, secret: str) -> None:
    """Better than an opaque signature failure from the venue."""
    with pytest.raises(InvariantViolation):
        BybitCredentials(api_key=key, api_secret=secret)


def test_a_non_positive_recv_window_is_refused(
    credentials: BybitCredentials,
) -> None:
    with pytest.raises(InvariantViolation, match="recv_window_ms must be positive"):
        BybitSigner(credentials, FrozenClock(), recv_window_ms=0)
