"""RED-first unit tests for the PURE helpers in ``check_key_permissions.py``
(redaction, the signing announcement, verdict formatting, field extraction
from fixture payloads) and the GET-only HTTP transport -- unit 1a.

No test here needs a real credential or the network: every venue call in the
script is excluded from this suite by construction, matching
``test_check_venue_fill_windows.py``'s precedent. The probe items themselves
are owner-run on the VPS, not part of CI.
"""

import httpx
import pytest
from check_key_permissions import (
    GetOnlyTransport,
    ItemVerdict,
    extract_binance_binding_expiry,
    extract_binance_restrictions,
    extract_bybit_binding_expiry,
    extract_bybit_trade_capability,
    extract_bybit_withdraw_shape,
    format_item_verdict,
    format_signing_line,
    redact_permissions_payload,
)

# --- redact_permissions_payload (task 1a.1) ----------------------------------


def test_redaction_masks_every_apikey_and_secret_field_to_last_four() -> None:
    """Pins the redaction rule against a fixture Bybit ``query-api`` payload
    that echoes ``apiKey`` -- the exact trap the design calls out."""
    real_key = "REALBYBITKEY1234"
    real_secret = "REALBYBITSECRET5678"
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "id": "abc123",
            "note": "worker key",
            "apiKey": real_key,
            "readOnly": 0,
            "permissions": {
                "Wallet": ["AccountTransfer"],
                "ContractTrade": ["Order", "Position"],
            },
            "ips": ["1.2.3.4"],
            "expiredAt": "",
            # A secret echoed under an unexpected field name -- the
            # name-only rule alone would miss this.
            "echoed_elsewhere": real_secret,
        },
    }

    redacted = redact_permissions_payload(payload, secrets=[real_key, real_secret])

    assert redacted["result"]["apiKey"] == "***1234"
    assert redacted["result"]["echoed_elsewhere"] == "***5678"
    # Every other field is untouched.
    assert redacted["result"]["readOnly"] == 0
    assert redacted["result"]["permissions"]["Wallet"] == ["AccountTransfer"]
    assert redacted["result"]["ips"] == ["1.2.3.4"]

    rendered = repr(redacted)
    assert real_key not in rendered
    assert real_secret not in rendered


def test_redaction_walks_lists_and_leaves_non_secret_strings_untouched() -> None:
    payload = {
        "result": [
            {"secret": "REALSECRETABCDEF"},
            {"note": "not a secret at all"},
        ]
    }

    redacted = redact_permissions_payload(payload, secrets=["REALSECRETABCDEF"])

    assert redacted["result"][0]["secret"] == "***CDEF"
    assert redacted["result"][1]["note"] == "not a secret at all"


def test_redaction_is_a_no_op_on_a_payload_with_no_secret_shape() -> None:
    payload = {"enableWithdrawals": False, "enableFutures": True, "ipRestrict": False}

    assert redact_permissions_payload(payload, secrets=["SOMEKEY1234"]) == payload


# --- format_signing_line (task 1a.2) -----------------------------------------


def test_announce_prints_last_four_and_source_never_the_full_value() -> None:
    api_key = "abcd1234wxyz"

    line = format_signing_line(api_key, "vault")

    assert line == "Signing as ***wxyz  (from the vault)"
    assert api_key not in line


def test_announce_refuses_a_key_too_short_to_redact_safely() -> None:
    with pytest.raises(ValueError):
        format_signing_line("abc", "vault")


# --- format_item_verdict (verdict formatting, pure) --------------------------


def test_format_item_verdict_answered() -> None:
    verdict = ItemVerdict("answered", "permissions.Wallet=[] -- cannot withdraw")

    rendered = format_item_verdict("P1", verdict)

    assert rendered == (
        "P1 Bybit withdraw shape: ANSWERED -- permissions.Wallet=[] -- cannot withdraw"
    )


def test_format_item_verdict_refused_carries_the_venues_own_code() -> None:
    verdict = ItemVerdict("refused", "retMsg='invalid key'", code="10003")

    rendered = format_item_verdict("P3", verdict)

    assert rendered == "P3 Binance apiRestrictions: REFUSED (10003) -- retMsg='invalid key'"


def test_format_item_verdict_unknown_is_never_conflated_with_refused() -> None:
    verdict = ItemVerdict("unknown", "timeout")

    rendered = format_item_verdict("P4", verdict)

    assert rendered == "P4 live reads (vault key): UNKNOWN -- timeout"


# --- field extraction from fixture payloads (P1/P2/P3/P5) --------------------


def test_extract_bybit_withdraw_shape_detects_withdraw_present() -> None:
    result = {"permissions": {"Wallet": ["Withdraw", "AccountTransfer"]}}

    verdict = extract_bybit_withdraw_shape(result)

    assert verdict.status == "answered"
    assert "CAN withdraw" in verdict.detail


def test_extract_bybit_withdraw_shape_detects_withdraw_absent() -> None:
    result = {"permissions": {"Wallet": ["AccountTransfer"]}}

    verdict = extract_bybit_withdraw_shape(result)

    assert verdict.status == "answered"
    assert "cannot withdraw" in verdict.detail


def test_extract_bybit_withdraw_shape_unknown_when_permissions_missing() -> None:
    verdict = extract_bybit_withdraw_shape({"readOnly": 0})

    assert verdict.status == "unknown"


def test_extract_bybit_trade_capability_reads_readonly_and_both_fields() -> None:
    result = {
        "readOnly": 0,
        "permissions": {"ContractTrade": ["Order"], "Derivatives": []},
    }

    verdict = extract_bybit_trade_capability(result)

    assert verdict.status == "answered"
    assert "readOnly=0" in verdict.detail
    assert "ContractTrade=['Order']" in verdict.detail
    assert "Derivatives=[]" in verdict.detail


def test_extract_bybit_binding_expiry_reads_all_three_fields() -> None:
    result = {"ips": ["1.2.3.4"], "expiredAt": "2027-01-01", "deadlineDay": 30}

    verdict = extract_bybit_binding_expiry(result)

    assert verdict.status == "answered"
    assert "ips=['1.2.3.4']" in verdict.detail
    assert "expiredAt='2027-01-01'" in verdict.detail
    assert "deadlineDay=30" in verdict.detail


def test_extract_binance_restrictions_reads_withdraw_and_futures_flags() -> None:
    payload = {
        "enableWithdrawals": False,
        "enableFutures": True,
        "enableInternalTransfer": True,
        "permitsUniversalTransfer": True,
        "ipRestrict": False,
    }

    verdict = extract_binance_restrictions(payload)

    assert verdict.status == "answered"
    assert "enableWithdrawals=False" in verdict.detail
    assert "enableFutures=True" in verdict.detail


def test_extract_binance_restrictions_unknown_when_required_field_missing() -> None:
    verdict = extract_binance_restrictions({"enableWithdrawals": False})

    assert verdict.status == "unknown"


def test_extract_binance_binding_expiry_reads_both_fields() -> None:
    payload = {"ipRestrict": True, "tradingAuthorityExpirationTime": 1893456000000}

    verdict = extract_binance_binding_expiry(payload)

    assert verdict.status == "answered"
    assert "ipRestrict=True" in verdict.detail
    assert "tradingAuthorityExpirationTime=1893456000000" in verdict.detail


# --- GetOnlyTransport: refuses anything other than GET -----------------------


async def test_get_only_transport_passes_a_get_through() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = GetOnlyTransport(httpx.MockTransport(handler))
    request = httpx.Request("GET", "https://example.invalid/v5/user/query-api")

    response = await transport.handle_async_request(request)

    assert response.status_code == 200


async def test_get_only_transport_refuses_a_post() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never reach the inner transport")

    transport = GetOnlyTransport(httpx.MockTransport(handler))
    request = httpx.Request("POST", "https://example.invalid/v5/order/create")

    with pytest.raises(RuntimeError, match="GET-only"):
        await transport.handle_async_request(request)


async def test_get_only_transport_refuses_a_delete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never reach the inner transport")

    transport = GetOnlyTransport(httpx.MockTransport(handler))
    request = httpx.Request("DELETE", "https://example.invalid/v5/order/cancel")

    with pytest.raises(RuntimeError, match="GET-only"):
        await transport.handle_async_request(request)
