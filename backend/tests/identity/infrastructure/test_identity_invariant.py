"""``assert_identity_configured``: the API refuses to start without a way to
know who is signed in, and without an admin (multi-user design AD1; tasks.md
A.4).

Each refusal names the setting to fix. None of them prints a value: the e-mail
is not secret, but nothing in a startup error needs it.
"""

import pytest

from strategy_manager.identity.infrastructure.identity_invariant import (
    assert_identity_configured,
)
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation

ACCESS = {"access_team_domain": "acme.cloudflareaccess.com", "access_aud": "aud-tag"}


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_access_with_an_admin_starts() -> None:
    assert_identity_configured(_settings(admin_email="owner@example.com", **ACCESS))


def test_a_dev_identity_with_an_admin_starts_in_dry_run() -> None:
    assert_identity_configured(
        _settings(admin_email="owner@example.com", dev_user_email="dev@example.com", dry_run=True)
    )


def test_nothing_configured_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="ADMIN_EMAIL"):
        assert_identity_configured(Settings(_env_file=None))


def test_no_admin_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="ADMIN_EMAIL"):
        assert_identity_configured(_settings(**ACCESS))


def test_an_admin_that_is_not_an_address_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="ADMIN_EMAIL"):
        assert_identity_configured(_settings(admin_email="owner", **ACCESS))


def test_no_identity_source_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="ACCESS_TEAM_DOMAIN"):
        assert_identity_configured(_settings(admin_email="owner@example.com"))


@pytest.mark.parametrize(
    "half",
    [{"access_team_domain": "acme.cloudflareaccess.com"}, {"access_aud": "aud-tag"}],
)
def test_half_an_access_configuration_is_refused(half: dict[str, str]) -> None:
    with pytest.raises(InvariantViolation, match="ACCESS_TEAM_DOMAIN and ACCESS_AUD"):
        assert_identity_configured(_settings(admin_email="owner@example.com", **half))


def test_access_and_a_dev_identity_together_are_refused() -> None:
    with pytest.raises(InvariantViolation, match="DEV_USER_EMAIL"):
        assert_identity_configured(
            _settings(admin_email="owner@example.com", dev_user_email="dev@example.com", **ACCESS)
        )


def test_a_dev_identity_is_refused_when_live() -> None:
    with pytest.raises(InvariantViolation, match="DEV_USER_EMAIL"):
        assert_identity_configured(
            _settings(
                admin_email="owner@example.com", dev_user_email="dev@example.com", dry_run=False
            )
        )


def test_a_dev_identity_that_is_not_an_address_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="DEV_USER_EMAIL"):
        assert_identity_configured(
            _settings(admin_email="owner@example.com", dev_user_email="dev", dry_run=True)
        )
