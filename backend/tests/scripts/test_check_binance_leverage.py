"""The pure readings of the H.9 probe (``scripts/check_binance_leverage.py``).

The probe talks to the live venue, so only what it concludes from a payload is
tested here: the pair's maximum leverage from ``leverageBracket``, and what the
``marginType`` spelling of ``symbolConfig`` means for ``_is_isolated``.
"""

import pytest
from check_binance_leverage import bracket_max, spelling_verdict


def _entry(symbol: str, *leverages: int) -> dict[str, object]:
    return {
        "symbol": symbol,
        "brackets": [
            {"bracket": index + 1, "initialLeverage": leverage}
            for index, leverage in enumerate(leverages)
        ],
    }


def test_the_maximum_is_the_highest_initial_leverage_of_the_pairs_brackets() -> None:
    payload = [_entry("ETHUSDT", 100, 75, 50), _entry("SOLUSDT", 50, 25, 10)]

    assert bracket_max(payload, "SOLUSDT") == 50


def test_a_single_object_answer_is_read_as_well_as_a_list() -> None:
    assert bracket_max(_entry("SOLUSDT", 20, 10), "SOLUSDT") == 20


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [_entry("ETHUSDT", 100)],
        [{"symbol": "SOLUSDT", "brackets": []}],
        [{"symbol": "SOLUSDT", "brackets": [{"bracket": 1}]}],
        [{"symbol": "SOLUSDT", "brackets": [{"bracket": 1, "initialLeverage": "20"}]}],
        [{"symbol": "SOLUSDT", "brackets": [{"bracket": 1, "initialLeverage": True}]}],
        "not a payload",
    ],
)
def test_a_payload_with_no_readable_maximum_for_the_pair_is_refused(payload: object) -> None:
    with pytest.raises(ValueError, match="SOLUSDT"):
        bracket_max(payload, "SOLUSDT")


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("ISOLATED", "ISOLATED, exactly as _is_isolated expects"),
        ("isolated", "isolated: isolated, in another case than ISOLATED"),
        ("CROSSED", "NOT isolated: CROSSED"),
        ("cross", "NOT isolated: cross"),
    ],
)
def test_the_spelling_is_reported_as_read(spelling: str, expected: str) -> None:
    assert spelling_verdict(spelling) == expected
