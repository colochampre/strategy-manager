"""Binance request signing.

The first test is the one that matters: Binance publishes a worked example in
its request-security documentation, and a signer that does not reproduce that
exact hex is wrong no matter what the others say.
"""

from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.binance.signer import (
    KEY_HEADER,
    BinanceCredentials,
    BinanceSigner,
    signature_for,
)

# Binance's documented HMAC example (Spot API docs, "SIGNED request security").
DOC_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
DOC_QUERY = (
    "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
    "&recvWindow=5000&timestamp=1499827319559"
)
DOC_SIGNATURE = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
NOW_MS = str(int(NOW.timestamp() * 1000))


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _signer(recv_window_ms: int = 5000) -> BinanceSigner:
    return BinanceSigner(
        BinanceCredentials(api_key="key-abcd", api_secret=DOC_SECRET),
        FrozenClock(),
        recv_window_ms=recv_window_ms,
    )


def test_the_documented_example_signs_to_the_documented_hex() -> None:
    assert signature_for(DOC_SECRET, DOC_QUERY) == DOC_SIGNATURE


def test_the_signature_covers_exactly_the_query_that_is_sent() -> None:
    signed = _signer().sign_get("/fapi/v3/account", {"symbol": "BTCUSDT"})

    query = urlsplit(signed.path_with_query).query
    unsigned, _, signature = query.rpartition("&signature=")

    assert signature == signature_for(DOC_SECRET, unsigned)


def test_signature_is_the_last_parameter_after_window_and_timestamp() -> None:
    signed = _signer().sign_get("/fapi/v1/symbolConfig", {"symbol": "ETHUSDT"})

    names = [name for name, _ in parse_qsl(urlsplit(signed.path_with_query).query)]

    assert names == ["symbol", "recvWindow", "timestamp", "signature"]


def test_parameter_order_is_preserved_and_never_sorted() -> None:
    signed = _signer().sign_get("/x", {"zeta": "1", "alpha": "2"})

    names = [name for name, _ in parse_qsl(urlsplit(signed.path_with_query).query)]

    assert names[:2] == ["zeta", "alpha"]


def test_the_timestamp_comes_from_the_injected_clock() -> None:
    signed = _signer().sign_get("/fapi/v1/multiAssetsMargin")

    params = dict(parse_qsl(urlsplit(signed.path_with_query).query))

    assert params["timestamp"] == NOW_MS
    assert params["recvWindow"] == "5000"


def test_only_the_key_travels_in_a_header_and_the_secret_travels_nowhere() -> None:
    signed = _signer().sign_get("/fapi/v3/account")

    assert dict(signed.headers) == {KEY_HEADER: "key-abcd"}
    assert DOC_SECRET not in signed.path_with_query


def test_credentials_never_render_the_secret() -> None:
    rendered = repr(BinanceCredentials(api_key="abcdefgh1234", api_secret="very-secret"))

    assert "very-secret" not in rendered
    assert "***1234" in rendered


@pytest.mark.parametrize(("key", "secret"), [("", "s"), ("k", "")])
def test_empty_credentials_are_refused_up_front(key: str, secret: str) -> None:
    with pytest.raises(InvariantViolation):
        BinanceCredentials(api_key=key, api_secret=secret)


@pytest.mark.parametrize("window", [0, -1, 60_001])
def test_a_recv_window_outside_binances_bounds_is_refused(window: int) -> None:
    with pytest.raises(InvariantViolation):
        _signer(recv_window_ms=window)
