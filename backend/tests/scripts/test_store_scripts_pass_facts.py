"""What each ``store_*_credentials.py`` script may claim about a key (tasks 6a.9, 6b.7).

Pionex has no inspector and no futures pool (design addendum, Q3), so its script
keeps sealing directly with ``KeyFacts.unrecorded(trade_capable=True)``: exactly
what it has always asserted, claiming no verification and no confirmation.

The Bybit and Binance scripts were folded onto ``SaveCredential`` in 6b.7. They
must never seal by themselves again, because a direct ``vault.store`` would skip
the key policy: no confirmation check, no live read, no withdraw refusal. That is
structural, because the scripts need a database, a master key and a venue to
run, none of which a test may require (rule 1).
"""

import ast
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_FOLDED = [
    "store_bybit_credentials.py",
    "store_binance_credentials.py",
    "credential_cli.py",
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


def test_pionex_seals_with_unrecorded_facts_trade_capable_true() -> None:
    calls = _store_calls("store_pionex_credentials.py")

    assert len(calls) == 1
    args = calls[0].args
    assert len(args) == 2, "store_pionex_credentials.py must pass the facts to vault.store"
    assert ast.unparse(args[1]) == "KeyFacts.unrecorded(trade_capable=True)"


@pytest.mark.parametrize("script", _FOLDED)
def test_folded_scripts_never_seal_directly_they_go_through_save_credential(
    script: str,
) -> None:
    assert _store_calls(script) == [], f"{script} must not call vault.store itself"


def test_folded_scripts_never_claim_unrecorded_facts() -> None:
    for script in _FOLDED:
        source = (_SCRIPTS_DIR / script).read_text(encoding="utf-8")
        assert "KeyFacts.unrecorded" not in source, script


def test_the_shared_saver_is_save_credential() -> None:
    source = (_SCRIPTS_DIR / "credential_cli.py").read_text(encoding="utf-8")

    assert "SaveCredential(" in source


def test_the_shared_saver_hands_save_credential_the_real_pool_writer_on_the_same_session() -> None:
    """Saving through a script enables the exchange's pool exactly as the API
    does: the writer is built on the SAME session as the vault, so the pool
    commits with the credential."""
    source = (_SCRIPTS_DIR / "credential_cli.py").read_text(encoding="utf-8")

    assert "SqlAlchemyCapitalPoolWriter(session)" in source
    assert "SqlAlchemyCredentialVault(session, cipher, clock)" in source


def test_the_pionex_script_is_not_folded_and_never_touches_a_pool() -> None:
    """Pionex is outside ``KNOWN_FUTURES_POOLS``: it offers no futures order
    placement, and its script seals directly."""
    source = (_SCRIPTS_DIR / "store_pionex_credentials.py").read_text(encoding="utf-8")

    for word in ("SaveCredential", "capital_pool", "CapitalPool", "known_pools", "enable("):
        assert word not in source, word
