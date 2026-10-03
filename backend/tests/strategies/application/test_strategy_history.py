"""``StrategyHistory``: the six counts a delete is refused on (design.md
addendum 9x, § B and § C). Pure value object, no I/O."""

import ast
from dataclasses import fields
from pathlib import Path

import pytest

import strategy_manager.strategies.application.ports as ports_module
from strategy_manager.strategies.application.ports import StrategyHistory

_KINDS = [
    "signals",
    "reservations",
    "execution_attempts",
    "ledger_entries",
    "booking_proposals",
    "enablement_events",
]


def _history(**non_zero: int) -> StrategyHistory:
    counts = {kind: 0 for kind in _KINDS}
    counts.update(non_zero)
    return StrategyHistory(**counts)


def test_the_six_kinds_are_the_fields_in_their_documented_order() -> None:
    assert [field.name for field in fields(StrategyHistory)] == _KINDS


def test_a_history_of_zeros_is_empty() -> None:
    assert _history().is_empty() is True


@pytest.mark.parametrize("kind", _KINDS)
def test_is_empty_only_when_all_six_counts_are_zero(kind: str) -> None:
    assert _history(**{kind: 1}).is_empty() is False


def test_blocking_names_only_the_nonzero_kinds_in_a_fixed_order() -> None:
    history = _history(enablement_events=4, signals=3, ledger_entries=2)

    blocking = history.blocking()

    assert list(blocking.items()) == [
        ("signals", 3),
        ("ledger_entries", 2),
        ("enablement_events", 4),
    ]


def test_blocking_of_an_empty_history_is_empty() -> None:
    assert _history().blocking() == {}


def test_the_ports_module_imports_no_type_of_another_module() -> None:
    tree = ast.parse(Path(ports_module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    leaked = sorted(
        name
        for name in imported
        if any(
            name.startswith(f"strategy_manager.{module}")
            for module in ("signals", "allocation", "execution", "ledger", "reconciliation")
        )
    )

    assert leaked == []
