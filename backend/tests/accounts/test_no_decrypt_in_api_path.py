"""Structural guard (decision 5, design.md § "The API process decrypts"): the
admin API's credential path never decrypts.

The API process holds no reason to see a plaintext key: ``PUT`` stores one
(``CredentialWriterPort`` has no ``load``) and ``GET`` shows a last4 and the
facts recorded at save time. The one method that decrypts is
``SqlAlchemyCredentialVault.load``, and it belongs to the worker, at signing
time (rule 8).

This test parses the two modules and looks for the ATTRIBUTE ``load`` being
called or otherwise referenced, so a comment or a docstring that mentions it
does not trip the test and a rename of a local variable cannot hide it. It
needs no database. The trade-capability adapter's own no-decrypt property has
a behavioural test beside it (``test_trade_capability_adapter.py``); this one
adds the same structural check for it.
"""

import ast
from pathlib import Path

import pytest

import strategy_manager.accounts.application.save_credential as save_credential_module
import strategy_manager.accounts.infrastructure.credentials_router as credentials_router_module
import strategy_manager.accounts.infrastructure.trade_capability_adapter as adapter_module

_GUARDED = {
    "credentials_router.py": credentials_router_module,
    "save_credential.py": save_credential_module,
    "trade_capability_adapter.py": adapter_module,
}


def _load_references(source: str) -> list[int]:
    """Line numbers of every ``<anything>.load`` attribute reference."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "load"
    ]


def test_credentials_router_and_save_credential_never_call_dot_load() -> None:
    offenders = {
        name: lines
        for name, module in _GUARDED.items()
        if (lines := _load_references(Path(str(module.__file__)).read_text(encoding="utf-8")))
    }

    assert offenders == {}, f"the API credential path references .load( at {offenders}"


def test_the_checker_itself_sees_a_load_call() -> None:
    """The guard above is only worth something if it can go red: a module that
    does call ``vault.load(...)`` (however it is spelled) must be reported."""
    assert _load_references("credential = await vault.load('bybit')") == [1]
    assert _load_references("x = self._vault.load") == [1]
    assert _load_references("# vault.load('bybit')\n'''vault.load()'''") == []


@pytest.mark.parametrize("name", sorted(_GUARDED))
def test_every_guarded_module_exists_and_parses(name: str) -> None:
    """A guarded file that moved would make the first test vacuous."""
    path = Path(str(_GUARDED[name].__file__))
    assert path.name == name
    assert ast.parse(path.read_text(encoding="utf-8")) is not None
