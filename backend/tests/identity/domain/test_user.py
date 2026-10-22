"""A user is the e-mail Cloudflare Access verified (multi-user decision 1).

The e-mail is the identity, so two spellings of one address must be one user:
Access reports what the identity provider sent, and a provider is free to keep
the case the person typed. Only surrounding whitespace and case are folded;
nothing else about the address is reinterpreted.
"""

import pytest

from strategy_manager.identity.domain.user import InvalidEmailError, normalize_email


def test_case_and_surrounding_whitespace_are_folded() -> None:
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"


def test_an_already_normal_address_is_unchanged() -> None:
    assert normalize_email("owner@example.com") == "owner@example.com"


@pytest.mark.parametrize("raw", ["", "   ", "owner", "@example.com", "owner@", "a b@example.com"])
def test_something_that_is_not_an_address_is_refused(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalize_email(raw)
