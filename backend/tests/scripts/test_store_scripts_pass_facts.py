"""The three ``store_*_credentials.py`` scripts keep working once 0027 drops the
column defaults (task 6a.9).

``vault.store(credential, facts)`` now requires the facts. Until 8a-2 folds the
Bybit and Binance scripts onto ``SaveCredential`` (and 6b.7 gives Binance its
two confirmation flags), each script states exactly what it has always
asserted and nothing more: ``KeyFacts.unrecorded(trade_capable=True)``. The
scripts refused a key they could not see trading before sealing it, so ``True``
is the value they already acted on, and ``UNRECORDED`` claims no verification
and no confirmation.

Structural, because the scripts need a database, a master key and a venue to
run, none of which a test may require (rule 1).
"""

import ast
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_SCRIPTS = [
    "store_pionex_credentials.py",
    "store_bybit_credentials.py",
    "store_binance_credentials.py",
]


def _store_calls(script: str) -> list[ast.Call]:
    tree = ast.parse((_SCRIPTS_DIR / script).read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "store"
    ]


@pytest.mark.parametrize("script", _SCRIPTS)
def test_store_script_seals_with_unrecorded_facts_trade_capable_true(script: str) -> None:
    calls = _store_calls(script)

    assert len(calls) == 1, script
    args = calls[0].args
    assert len(args) == 2, f"{script} must pass the facts to vault.store"
    assert ast.unparse(args[1]) == "KeyFacts.unrecorded(trade_capable=True)"
