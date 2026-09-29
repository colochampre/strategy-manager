"""``ExchangeCredential`` / ``CredentialHint`` — CLAUDE.md rule 8.

A credential never reaches a client beyond a last-4 hint. The repr is part of
that guarantee, not a nicety: tracebacks and log lines are where secrets
usually escape.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
    FactSource,
    KeyFacts,
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


def test_the_hint_carries_nothing_but_the_last_four_and_the_recorded_facts() -> None:
    facts = KeyFacts.unrecorded(trade_capable=True)

    hint = _credential().hint(facts)

    assert hint == CredentialHint(
        exchange="pionex", label="default", api_key_last4="abcd", facts=facts
    )
    assert SECRET not in repr(hint)
    assert KEY not in repr(hint)


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


# --- KeyFacts (task 6a.6, design addendum section D) -------------------------

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _facts(**overrides: object) -> KeyFacts:
    """A fully recorded, Bybit-style key, with any field overridden."""
    fields: dict[str, object] = {
        "trade_capable": True,
        "trade_capability_source": FactSource.VERIFIED,
        "trade_confirmed_at": None,
        "withdraw_check": FactSource.VERIFIED,
        "withdraw_confirmed_at": None,
        "validated_at": NOW,
        "internal_transfer": True,
    }
    fields.update(overrides)
    return KeyFacts(**fields)  # type: ignore[arg-type]


def test_key_facts_owner_confirmed_requires_its_timestamp() -> None:
    confirmed = _facts(
        trade_capability_source=FactSource.OWNER_CONFIRMED,
        trade_confirmed_at=NOW,
        withdraw_check=FactSource.OWNER_CONFIRMED,
        withdraw_confirmed_at=NOW,
        internal_transfer=None,
    )
    assert confirmed.trade_confirmed_at == NOW

    with pytest.raises(InvariantViolation, match="trade"):
        _facts(trade_capability_source=FactSource.OWNER_CONFIRMED, trade_confirmed_at=None)
    with pytest.raises(InvariantViolation, match="withdraw"):
        _facts(withdraw_check=FactSource.OWNER_CONFIRMED, withdraw_confirmed_at=None)
    # ...and the timestamp requires the confirmation.
    with pytest.raises(InvariantViolation, match="trade"):
        _facts(trade_confirmed_at=NOW)
    with pytest.raises(InvariantViolation, match="withdraw"):
        _facts(withdraw_confirmed_at=NOW)


def test_key_facts_owner_confirmation_is_of_a_capability_never_an_incapability() -> None:
    with pytest.raises(InvariantViolation, match="incapability"):
        _facts(
            trade_capable=False,
            trade_capability_source=FactSource.OWNER_CONFIRMED,
            trade_confirmed_at=NOW,
        )


def test_key_facts_unrecorded_requires_no_timestamps_and_both_sources_together() -> None:
    legacy = KeyFacts.unrecorded(trade_capable=True)
    assert legacy.trade_capability_source is FactSource.UNRECORDED
    assert legacy.withdraw_check is FactSource.UNRECORDED
    assert legacy.validated_at is None
    assert legacy.internal_transfer is None

    # Half recorded, half legacy: refused in both directions.
    with pytest.raises(InvariantViolation, match="recorded"):
        _facts(trade_capability_source=FactSource.UNRECORDED)
    with pytest.raises(InvariantViolation, match="recorded"):
        _facts(withdraw_check=FactSource.UNRECORDED)
    # A recorded key was validated; a legacy one was not.
    with pytest.raises(InvariantViolation, match="validated"):
        _facts(validated_at=None)
    with pytest.raises(InvariantViolation, match="validated"):
        _facts(
            trade_capability_source=FactSource.UNRECORDED,
            withdraw_check=FactSource.UNRECORDED,
        )


def test_key_facts_a_source_outside_the_three_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="source"):
        _facts(trade_capability_source="BOGUS")


def test_key_facts_has_no_default_every_constructor_names_every_field() -> None:
    fields = dataclasses.fields(KeyFacts)

    assert [f.name for f in fields] == [
        "trade_capable",
        "trade_capability_source",
        "trade_confirmed_at",
        "withdraw_check",
        "withdraw_confirmed_at",
        "validated_at",
        "internal_transfer",
    ]
    for field in fields:
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name
    with pytest.raises(TypeError):
        KeyFacts()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        KeyFacts(trade_capable=True)  # type: ignore[call-arg]


def test_key_facts_unrecorded_is_the_only_named_constructor() -> None:
    constructors = {
        name
        for name, member in vars(KeyFacts).items()
        if isinstance(member, classmethod) and not name.startswith("_")
    }
    assert constructors == {"unrecorded"}
    assert KeyFacts.unrecorded(trade_capable=False).trade_capable is False
