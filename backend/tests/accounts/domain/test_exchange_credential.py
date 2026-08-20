"""``ExchangeCredential`` / ``CredentialHint`` — CLAUDE.md rule 8.

A credential never reaches a client beyond a last-4 hint. The repr is part of
that guarantee, not a nicety: tracebacks and log lines are where secrets
usually escape.
"""

import pytest

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
)
from strategy_manager.shared.domain.errors import InvariantViolation

KEY = "PIONEX-KEY-abcd"
SECRET = "PIONEX-SECRET-wxyz"


def _credential(api_key: str = KEY, api_secret: str = SECRET) -> ExchangeCredential:
    return ExchangeCredential(
        exchange="pionex", label="default", api_key=api_key, api_secret=api_secret
    )


def test_last4_is_the_tail_of_the_api_key() -> None:
    assert _credential().last4 == "abcd"


def test_the_hint_carries_nothing_but_the_last_four() -> None:
    hint = _credential().hint()

    assert hint == CredentialHint(
        exchange="pionex", label="default", api_key_last4="abcd"
    )


def test_repr_shows_neither_the_secret_nor_the_full_key() -> None:
    rendered = repr(_credential())

    assert SECRET not in rendered
    assert KEY not in rendered
    assert "abcd" in rendered


@pytest.mark.parametrize(
    ("api_key", "api_secret"),
    [("", SECRET), (KEY, "")],
)
def test_empty_values_are_rejected(api_key: str, api_secret: str) -> None:
    with pytest.raises(InvariantViolation):
        _credential(api_key=api_key, api_secret=api_secret)


def test_a_key_too_short_to_hint_is_rejected() -> None:
    """A three-character key would make ``last4`` silently return the whole
    key, turning the hint into the secret."""
    with pytest.raises(InvariantViolation, match="at least 4"):
        _credential(api_key="abc")
