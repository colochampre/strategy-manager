"""``assert_admin_api_token_configured`` — startup invariant 4.

The configuration this catches reports nothing. The API starts, the strategies
router mounts, and the only thing keeping registration and arming off the
public internet is ``AdminTokenAuth`` failing closed on an empty expected
value — one line, and a reverse-proxy rule the application does not control.
"""

import pytest

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.infrastructure.admin_token_invariant import (
    assert_admin_api_token_configured,
)


def _settings(token: str, dry_run: bool = True) -> Settings:
    """Built without reading .env, so these assertions describe the code and
    not whatever the developer's machine happens to be configured with."""
    return Settings(
        admin_api_token=token,
        dry_run=dry_run,
        _env_file=None,  # type: ignore[call-arg]
    )


def test_a_configured_token_starts_normally() -> None:
    assert_admin_api_token_configured(_settings("adm1n-t0ken"))


def test_an_empty_token_refuses_to_start() -> None:
    with pytest.raises(InvariantViolation, match="ADMIN_API_TOKEN is not set"):
        assert_admin_api_token_configured(_settings(""))


def test_the_default_configuration_refuses_to_start() -> None:
    """``admin_api_token`` defaults to empty, so a deployment that sets nothing
    hits this rather than serving its admin API to whoever can reach it."""
    with pytest.raises(InvariantViolation):
        assert_admin_api_token_configured(Settings(_env_file=None))


def test_the_failure_says_how_to_generate_one() -> None:
    """An operator reading this in a crash log needs the recipe, not just the
    name of a variable."""
    with pytest.raises(InvariantViolation, match="token_urlsafe"):
        assert_admin_api_token_configured(_settings(""))


def test_a_dry_run_is_refused_just_the_same() -> None:
    """A rehearsal writes the same strategy rows a live process reads, so an
    open admin API is a production configuration one variable later."""
    with pytest.raises(InvariantViolation):
        assert_admin_api_token_configured(_settings("", dry_run=True))
