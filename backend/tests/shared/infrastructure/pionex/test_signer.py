import hmac
from hashlib import sha256

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.pionex.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    PionexCredentials,
    PionexSigner,
)

BALANCES = "/api/v1/account/balances"


def _hmac_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


def test_signs_the_literal_method_path_and_query_concatenation(
    signer: PionexSigner, api_secret: str, timestamp_ms: int
) -> None:
    """The payload shape is the whole risk: a wrong concatenation produces a
    perfectly valid-looking hex digest that Pionex rejects every time."""
    signed = signer.sign("GET", BALANCES)

    expected_payload = f"GET{BALANCES}?timestamp={timestamp_ms}"
    assert signed.headers[SIGNATURE_HEADER] == _hmac_hex(api_secret, expected_payload)


def test_path_with_query_is_what_was_signed(
    signer: PionexSigner, timestamp_ms: int
) -> None:
    signed = signer.sign("GET", BALANCES)

    assert signed.path_with_query == f"{BALANCES}?timestamp={timestamp_ms}"


def test_query_parameters_are_sorted_ascending_by_ascii_key(
    signer: PionexSigner, timestamp_ms: int
) -> None:
    signed = signer.sign(
        "GET",
        "/uapi/v1/account/leverage",
        {"symbol": "BTC_USDT", "limit": "1"},
    )

    assert signed.path_with_query == (
        f"/uapi/v1/account/leverage?limit=1&symbol=BTC_USDT&timestamp={timestamp_ms}"
    )


def test_the_method_is_upper_cased_in_the_payload(
    signer: PionexSigner, api_secret: str, timestamp_ms: int
) -> None:
    signed = signer.sign("get", BALANCES)

    expected_payload = f"GET{BALANCES}?timestamp={timestamp_ms}"
    assert signed.headers[SIGNATURE_HEADER] == _hmac_hex(api_secret, expected_payload)


def test_signature_is_lowercase_hex(signer: PionexSigner) -> None:
    signature = signer.sign("GET", BALANCES).headers[SIGNATURE_HEADER]

    assert len(signature) == 64
    assert signature == signature.lower()


def test_the_api_key_travels_in_its_own_header(signer: PionexSigner) -> None:
    assert signer.sign("GET", BALANCES).headers[KEY_HEADER] == "test-key-abcd"


def test_a_value_needing_url_encoding_is_rejected(signer: PionexSigner) -> None:
    """Pionex signs raw values. A space would be encoded on the wire but not
    in the payload, so the request could never authenticate."""
    with pytest.raises(InvariantViolation, match="URL-safe"):
        signer.sign("GET", BALANCES, {"symbol": "BTC USDT"})


def test_a_caller_supplied_timestamp_is_rejected(signer: PionexSigner) -> None:
    with pytest.raises(InvariantViolation, match="timestamp"):
        signer.sign("GET", BALANCES, {"timestamp": "1"})


@pytest.mark.parametrize(
    ("api_key", "secret"),
    [("", "a-secret"), ("a-key", "")],
)
def test_empty_credentials_are_rejected(api_key: str, secret: str) -> None:
    with pytest.raises(InvariantViolation):
        PionexCredentials(api_key=api_key, api_secret=secret)


def test_repr_leaks_neither_the_secret_nor_the_full_key(
    credentials: PionexCredentials, api_secret: str
) -> None:
    rendered = repr(credentials)

    assert api_secret not in rendered
    assert credentials.api_key not in rendered
    assert "abcd" in rendered
