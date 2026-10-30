"""A webhook secret's last four characters: what the panel masks it with (multi-user
design, decision 25; tasks.md H.1)."""

import pytest

from strategy_manager.strategies.domain.webhook_secret import (
    new_webhook_secret,
    webhook_secret_last4,
)


def test_the_last_four_are_the_last_four_characters_of_the_secret() -> None:
    assert webhook_secret_last4("abcdefghij") == "ghij"


def test_a_four_character_secret_is_its_own_last_four() -> None:
    assert webhook_secret_last4("wxyz") == "wxyz"


def test_a_generated_secret_ends_with_its_last_four() -> None:
    secret = new_webhook_secret()

    assert webhook_secret_last4(secret) == secret[-4:]
    assert len(webhook_secret_last4(secret)) == 4


def test_a_secret_shorter_than_four_has_no_last_four_and_the_refusal_names_none_of_it() -> None:
    with pytest.raises(ValueError) as caught:
        webhook_secret_last4("abc")

    assert "abc" not in str(caught.value)
