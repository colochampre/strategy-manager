"""Structural guard (rule 8, decision 41): the API process reads the venues'
catalogues WITHOUT a credential.

The public catalogue sources and the adapter and router that serve them are
built on transports whose constructors take an HTTP client and nothing else.
Nothing in these four modules may import a signer, the vault or the cipher:
the day one does, the API process has a way to authenticate and a key to do it
with, and the property "no credential in the API process" is gone without any
test of behaviour noticing.

The test reads the modules' IMPORTS from their syntax trees, so a comment or a
docstring that mentions a signer does not trip it, and a renamed alias cannot
hide one. It needs no database and no network.
"""

import ast
from pathlib import Path

import pytest

import strategy_manager.shared.infrastructure.binance.public_catalogue as binance_catalogue
import strategy_manager.shared.infrastructure.bybit.public_catalogue as bybit_catalogue
import strategy_manager.strategies.infrastructure.pair_catalog as pair_catalog
import strategy_manager.strategies.infrastructure.pair_catalog_router as pair_catalog_router

_GUARDED = {
    "bybit/public_catalogue.py": bybit_catalogue,
    "binance/public_catalogue.py": binance_catalogue,
    "strategies/infrastructure/pair_catalog.py": pair_catalog,
    "strategies/infrastructure/pair_catalog_router.py": pair_catalog_router,
}

#: A module path containing any of these words is a credential-bearing module.
_FORBIDDEN_MODULE_WORDS = ("signer", "vault", "crypto", "cipher", "credential")

#: Names that carry a credential or a way to sign, whichever module they come from.
_FORBIDDEN_NAMES = frozenset(
    {
        "BybitSigner",
        "BinanceSigner",
        "BybitCredentials",
        "BinanceCredentials",
        "BybitTransport",
        "BinanceTransport",
        "EnvelopeCipher",
        "SqlAlchemyCredentialVault",
        "ExchangeCredential",
    }
)


def _offences(source: str) -> list[str]:
    """Every import in ``source`` that brings in a signer, the vault or the cipher."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            pairs = [(alias.name, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            pairs = [(node.module or "", alias.name) for alias in node.names]
        else:
            continue
        for module, name in pairs:
            lowered = module.lower()
            if name in _FORBIDDEN_NAMES or any(w in lowered for w in _FORBIDDEN_MODULE_WORDS):
                found.append(f"line {node.lineno}: {module} -> {name}")
    return found


def test_public_catalogue_modules_import_no_signer_vault_or_cipher() -> None:
    offenders = {
        name: offences
        for name, module in _GUARDED.items()
        if (offences := _offences(Path(str(module.__file__)).read_text(encoding="utf-8")))
    }

    assert offenders == {}, f"a credential-bearing import reached the catalogue path: {offenders}"


def test_the_checker_itself_sees_a_signer_a_vault_and_a_cipher() -> None:
    """The guard is only worth something if it can go red, however the import
    is spelled. Comments and docstrings stay out of it."""
    cases = [
        "from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner",
        "from strategy_manager.shared.infrastructure.binance.signer import BinanceSigner as S",
        "from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher",
        "from strategy_manager.accounts.infrastructure.credential_vault import X",
        "import strategy_manager.shared.infrastructure.bybit.signer",
        "from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport",
    ]
    for source in cases:
        assert _offences(source), source
    assert _offences("# from x.signer import BybitSigner\n'''import vault'''") == []
    assert _offences("from strategy_manager.shared.infrastructure.bybit.transport import (\n"
                     "    BybitPublicTransport,\n)") == []


@pytest.mark.parametrize("name", sorted(_GUARDED))
def test_every_guarded_module_exists_and_parses(name: str) -> None:
    """A guarded file that moved would make the first test vacuous."""
    path = Path(str(_GUARDED[name].__file__))
    assert path.as_posix().endswith(name)
    assert ast.parse(path.read_text(encoding="utf-8")) is not None
