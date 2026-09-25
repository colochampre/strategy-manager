"""Unit tests for the ``AllowedPairs`` VO (design.md § 6 "Allowed pairs: an
array column, migration 0024"; spec: strategy-lifecycle § "Allowed-Pairs
List Per Strategy").

The VO only asserts the SHAPE of its entries -- non-empty, upper-case, no
whitespace. Normalizing a raw signal symbol into that shape (``market_key()``)
is application work (``RegisterStrategy``, ``ReplaceAllowedPairs``), not
tested here (tasks.md 2a.2).
"""

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs


def test_allowed_pairs_rejects_empty_string_entry() -> None:
    with pytest.raises(InvariantViolation):
        AllowedPairs(frozenset({"SOLUSDT", ""}))


def test_allowed_pairs_rejects_lowercase_entry() -> None:
    with pytest.raises(InvariantViolation):
        AllowedPairs(frozenset({"solusdt"}))


def test_allowed_pairs_stores_sorted() -> None:
    """The domain holds a ``frozenset`` (unordered); ``design.md`` § 6 says
    it is "stored sorted" -- the DB column and the API both need a stable
    order, not the arbitrary iteration order of a set."""
    pairs = AllowedPairs(frozenset({"SOLUSDT", "ETHUSDT", "BTCUSDT"}))

    assert pairs.sorted() == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
