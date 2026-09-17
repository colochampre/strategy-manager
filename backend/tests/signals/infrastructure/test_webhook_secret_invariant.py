"""``assert_webhook_secret_configured`` — startup invariant 3.

The configuration this catches reports nothing. The API starts, the endpoint
answers, and every alert is answered 401 by an authentication that fails closed
on an empty expected secret — which reads exactly like a strategy that never
fired.
"""

import pytest

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.infrastructure.webhook_secret_invariant import (
    assert_webhook_secret_configured,
)


def _settings(secret: str, dry_run: bool = True) -> Settings:
    """Built without reading .env, so these assertions describe the code and
    not whatever the developer's machine happens to be configured with."""
    return Settings(
        webhook_secret=secret,
        dry_run=dry_run,
        _env_file=None,  # type: ignore[call-arg]
    )


def test_a_configured_secret_starts_normally() -> None:
    assert_webhook_secret_configured(_settings("s3cr3t"))


def test_an_empty_secret_refuses_to_start() -> None:
    with pytest.raises(InvariantViolation, match="WEBHOOK_SECRET is not set"):
        assert_webhook_secret_configured(_settings(""))


def test_the_default_configuration_refuses_to_start() -> None:
    """``webhook_secret`` defaults to empty, so a deployment that sets nothing
    hits this rather than dropping every alert in silence."""
    with pytest.raises(InvariantViolation):
        assert_webhook_secret_configured(Settings(_env_file=None))


def test_the_failure_says_how_to_generate_one() -> None:
    """An operator reading this in a crash log needs the recipe, not just the
    name of a variable."""
    with pytest.raises(InvariantViolation, match="token_urlsafe"):
        assert_webhook_secret_configured(_settings(""))


def test_a_dry_run_is_refused_just_the_same() -> None:
    """A rehearsal still ingests signals — that is most of what a dry run is
    for — so an empty secret breaks it exactly as thoroughly."""
    with pytest.raises(InvariantViolation):
        assert_webhook_secret_configured(_settings("", dry_run=True))
