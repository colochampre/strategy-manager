"""``TradingViewAlert.from_payload`` refuses a body the ``signals`` table cannot hold.

Task 9qf.7. The whole parsed body is stored verbatim in ``signals.raw_payload``
(``JSONB``) and ``symbol``, ``action`` and ``signal_type`` are ``text``. PostgreSQL
refuses a NUL character in either, JSON cannot hold a number that is not finite,
and a lone surrogate cannot be encoded as UTF-8. Each used to reach the insert or
the idempotency key and answer an unhandled 500. The refusal is made here, in the
domain, so nothing can store a body that skipped it.

The check is ONE ITERATIVE pass: a recursive walk of a body nested 100,000 levels
deep would raise the very ``RecursionError`` this task removes. The depth tests
build their bodies with a loop for the same reason.

Every refusal carries ``field="body"`` and a fixed reason. A key or a value the
sender supplied is never in the text.
"""

import copy
import math
from typing import Any

import pytest

from strategy_manager.signals.domain.alert import (
    AlertParsingError,
    TradingViewAlert,
    derive_idempotency_key,
)

VALID_PAYLOAD: dict[str, Any] = {
    "data": {"action": "buy", "contracts": "10", "position_size": "10"},
    "price": "50000.5",
    "signal_param": "{}",
    "signal_type": "a6a28229-9286-463f-99e8-5f48eb597d19",
    "symbol": "BTCUSDT",
    "time": "2026-08-12T10:15:30Z",
}

# sha256 of "<signal_type>|<time>|buy|10|10", computed before this task changed
# anything: an accepted alert must keep exactly this key.
VALID_PAYLOAD_KEY = "d378813315d0273839d8bda59a251e66ee31b6cc2b649d1f03a6cc9639493943"

CHARACTER_REASON = "contains a character that cannot be stored"
NUMBER_REASON = "contains a number that is not finite"
DEPTH_REASON = "is nested too deeply"

NUL = "\x00"
SURROGATE = "\ud800"
BAD_CHARACTERS = [pytest.param(NUL, id="nul"), pytest.param(SURROGATE, id="lone-surrogate")]
NON_FINITE = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="infinity"),
    pytest.param(-math.inf, id="minus-infinity"),
]

# The deepest body the parser accepts: the body is level 1 and ``data`` level 2.
BOUND = 64


def _nested_lists(levels: int) -> Any:
    node: Any = []
    for _ in range(levels - 1):
        node = [node]
    return node


def _nested_objects(levels: int) -> Any:
    node: Any = {}
    for _ in range(levels - 1):
        node = {"a": node}
    return node


def _with(**extra: Any) -> dict[str, Any]:
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload.update(extra)
    return payload


def _refusal(payload: Any) -> AlertParsingError | None:
    try:
        TradingViewAlert.from_payload(payload)
    except AlertParsingError as exc:
        return exc
    return None


def _log_text(payload: Any) -> str:
    refusal = _refusal(payload)
    assert refusal is not None
    return refusal.log_text


def _string_placements(value: str) -> list[tuple[str, dict[str, Any]]]:
    """Every place the alert's own strings and the stored body can carry ``value``."""

    in_data = copy.deepcopy(VALID_PAYLOAD)
    in_data["data"]["action"] = f"a{value}b"
    extra_in_data = copy.deepcopy(VALID_PAYLOAD)
    extra_in_data["data"]["extra"] = f"a{value}b"
    return [
        ("data.action", in_data),
        ("symbol", _with(symbol=f"A{value}B")),
        ("signal_type", _with(signal_type=f"a{value}b")),
        ("time", _with(time=f"a{value}b")),
        ("signal_param", _with(signal_param=f"a{value}b")),
        ("extra top-level key", _with(extra=f"a{value}b")),
        ("extra key inside data", extra_in_data),
        ("nested object value", _with(extra={"y": {"z": f"a{value}b"}})),
        ("array element", _with(extra=["ok", [f"a{value}b"]])),
        ("top-level object key", _with(**{f"k{value}": 1})),
        ("nested object key", _with(extra={"y": {f"k{value}": 1}})),
        ("key of an object in an array", _with(extra=[{f"k{value}": 1}])),
    ]


@pytest.mark.parametrize("value", BAD_CHARACTERS)
def test_a_nul_or_a_lone_surrogate_anywhere_in_the_body_is_refused(value: str) -> None:
    for place, payload in _string_placements(value):
        refusal = _refusal(payload)
        assert refusal is not None, place
        assert refusal.field == "body", place
        assert refusal.reason == CHARACTER_REASON, place


@pytest.mark.parametrize("value", BAD_CHARACTERS)
def test_the_character_refusal_has_a_log_text_and_a_detail_without_the_value(value: str) -> None:
    payload = _with(**{"MARKER-KEY" + value: "MARKER-VALUE"})

    refusal = _refusal(payload)

    assert refusal is not None
    assert refusal.log_text == f"body {CHARACTER_REASON}"
    for text in (refusal.log_text, str(refusal)):
        assert "MARKER" not in text
        assert value not in text


@pytest.mark.parametrize("number", NON_FINITE)
def test_a_number_that_is_not_finite_anywhere_in_the_body_is_refused(number: float) -> None:
    placements = [
        _with(extra=number),
        _with(extra=[1, [number]]),
        _with(extra={"y": {"z": number}}),
        _with(extra=[{"y": number}]),
    ]
    inside_data = copy.deepcopy(VALID_PAYLOAD)
    inside_data["data"]["extra"] = number
    placements.append(inside_data)

    for payload in placements:
        refusal = _refusal(payload)
        assert refusal is not None
        assert refusal.field == "body"
        assert refusal.reason == NUMBER_REASON
        assert refusal.log_text == f"body {NUMBER_REASON}"
        assert str(refusal) == f"body {NUMBER_REASON}"


@pytest.mark.parametrize("make", [_nested_lists, _nested_objects], ids=["lists", "objects"])
def test_a_body_at_the_depth_bound_is_accepted(make: Any) -> None:
    # The extra value is level 2 and ``levels`` containers deep, so the body is
    # ``levels + 1`` deep in all.
    alert = TradingViewAlert.from_payload(_with(extra=make(BOUND - 1)))

    assert alert.symbol == "BTCUSDT"


@pytest.mark.parametrize("make", [_nested_lists, _nested_objects], ids=["lists", "objects"])
def test_a_body_one_level_past_the_depth_bound_is_refused(make: Any) -> None:
    assert _log_text(_with(extra=make(BOUND))) == f"body {DEPTH_REASON}"


@pytest.mark.parametrize("make", [_nested_lists, _nested_objects], ids=["lists", "objects"])
@pytest.mark.parametrize("levels", [1_000, 10_000, 100_000])
def test_a_body_nested_far_past_the_bound_is_refused_without_recursing(
    make: Any, levels: int
) -> None:
    # A recursive walk would raise ``RecursionError`` here instead of refusing.
    assert _log_text(_with(extra=make(levels))) == f"body {DEPTH_REASON}"


def test_the_depth_refusal_names_the_body_and_carries_no_value() -> None:
    refusal = _refusal(_with(extra=_nested_lists(BOUND)))

    assert refusal is not None
    assert (refusal.field, refusal.reason) == ("body", DEPTH_REASON)
    assert str(refusal) == f"body {DEPTH_REASON}"


def test_the_depth_is_counted_from_the_body_not_from_a_branch() -> None:
    wide = _with(extra=[_nested_lists(BOUND - 2) for _ in range(50)])

    assert TradingViewAlert.from_payload(wide).symbol == "BTCUSDT"


def test_the_valid_alert_is_accepted_and_keeps_its_idempotency_key() -> None:
    alert = TradingViewAlert.from_payload(copy.deepcopy(VALID_PAYLOAD))

    assert derive_idempotency_key(alert) == VALID_PAYLOAD_KEY


def test_an_alert_with_text_and_an_unknown_key_is_accepted_unchanged() -> None:
    payload = _with(
        signal_param="{}",
        symbol="ETHUSDTé",
        note="café 中文 \U0001f680 \\u0000",
        extra={"nested": ["a", 1, 1.5, True, None, {"ké": "v"}]},
    )
    before = copy.deepcopy(payload)

    alert = TradingViewAlert.from_payload(payload)

    assert alert.symbol == "ETHUSDTé"
    assert payload == before
    assert derive_idempotency_key(alert) == VALID_PAYLOAD_KEY


@pytest.mark.parametrize(
    "number",
    [0.0, -0.0, 1e308, -1e308, 1e-320, pytest.param(10**400, id="401-digit-integer")],
)
def test_a_finite_number_anywhere_in_the_body_is_accepted(number: float) -> None:
    assert TradingViewAlert.from_payload(_with(extra=[number])).symbol == "BTCUSDT"
