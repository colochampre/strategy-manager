"""The pure half of decision 41: which candidate pairs a venue does not list.

Every symbol here is already in ``market_key`` form: normalizing is the
adapter's and the use cases' job, and this rule only compares two sets.
"""

import ast
from pathlib import Path

import strategy_manager.strategies.domain.pair_catalog as pair_catalog_module
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
    PairsChangedConcurrently,
    UnknownPairs,
    unknown_pairs,
)

_ERRORS = (UnknownPairs, PairCatalogUnavailable, PairCatalogNotServed, PairsChangedConcurrently)


def test_unknown_pairs_is_the_sorted_difference_of_candidates_and_available() -> None:
    result = unknown_pairs(
        ["YPFUSDT", "STXUSDT", "AAVEUSDT", "BTCUSDT"],
        frozenset({"BTCUSDT", "STXUSDT", "ETHUSDT"}),
    )

    assert result == ("AAVEUSDT", "YPFUSDT")


def test_unknown_pairs_of_a_fully_listed_request_is_empty() -> None:
    assert unknown_pairs(["BTCUSDT"], frozenset({"BTCUSDT", "ETHUSDT"})) == ()


def test_unknown_pairs_error_carries_the_symbols_as_a_sorted_tuple() -> None:
    error = UnknownPairs({"YPFUSDT", "AAVEUSDT", "ZZZUSDT"})

    assert error.unknown == ("AAVEUSDT", "YPFUSDT", "ZZZUSDT")
    assert isinstance(error.unknown, tuple)


def test_the_four_errors_are_distinct_domain_errors() -> None:
    for error in _ERRORS:
        assert issubclass(error, DomainError)
    # No error is a kind of another: a handler for one must never swallow a
    # different one (an unreadable venue is not an unknown pair).
    for error in _ERRORS:
        for other in _ERRORS:
            if error is not other:
                assert not issubclass(error, other), f"{error.__name__} is a {other.__name__}"


def test_domain_module_imports_no_framework() -> None:
    tree = ast.parse(Path(str(pair_catalog_module.__file__)).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"fastapi", "sqlalchemy", "httpx", "pydantic", "starlette", "asyncpg"}
    assert imported & forbidden == set()
