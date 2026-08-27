"""Unit tests for SourceIpAndSecretAuth.

Covers spec: signal-ingress § Webhook Authentication.
"""

from strategy_manager.shared.config import Settings
from strategy_manager.signals.infrastructure.auth import SourceIpAndSecretAuth

ALLOWED_IP = "52.89.214.238"
OTHER_ALLOWED_IP = "34.212.75.30"


def _settings(secret: str = "s3cr3t", extra: list[str] | None = None) -> Settings:
    """Built without reading .env, so these assertions describe the code and
    not whatever the developer's machine happens to be configured with."""
    return Settings(
        webhook_secret=secret,
        extra_webhook_source_ips=extra or [],
        _env_file=None,  # type: ignore[call-arg]
    )


def test_valid_secret_and_ip_authenticates() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="s3cr3t")

    assert auth.authenticate(ALLOWED_IP, "s3cr3t") is True


def test_wrong_source_ip_rejected_even_with_correct_secret() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="s3cr3t")

    assert auth.authenticate("203.0.113.9", "s3cr3t") is False


def test_missing_secret_rejected() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="s3cr3t")

    assert auth.authenticate(ALLOWED_IP, None) is False


def test_wrong_secret_rejected() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="s3cr3t")

    assert auth.authenticate(ALLOWED_IP, "wrong") is False


def test_unconfigured_expected_secret_never_authenticates() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="")

    assert auth.authenticate(ALLOWED_IP, "") is False


def test_only_the_four_documented_ips_are_allowed() -> None:
    auth = SourceIpAndSecretAuth(expected_secret="s3cr3t")

    assert auth.authenticate(OTHER_ALLOWED_IP, "s3cr3t") is True
    assert auth.authenticate(None, "s3cr3t") is False


def test_by_default_only_tradingviews_addresses_are_accepted() -> None:
    """The extra list is empty unless a deployment sets it, so configuring
    nothing behaves exactly as before."""
    auth = SourceIpAndSecretAuth.from_settings(_settings())

    assert auth.authenticate(ALLOWED_IP, "s3cr3t") is True
    assert auth.authenticate("127.0.0.1", "s3cr3t") is False


def test_a_configured_address_is_accepted_alongside_tradingviews() -> None:
    """Without this the ingress path cannot be rehearsed at all: an alert has
    to come from one of four fixed addresses, so nobody can send themselves a
    test one."""
    auth = SourceIpAndSecretAuth.from_settings(_settings(extra=["127.0.0.1"]))

    assert auth.authenticate("127.0.0.1", "s3cr3t") is True


def test_configuration_can_only_widen_never_replace() -> None:
    """No configuration may stop TradingView's own alerts from arriving, which
    is the one thing this endpoint exists for."""
    auth = SourceIpAndSecretAuth.from_settings(_settings(extra=["127.0.0.1"]))

    assert auth.authenticate(ALLOWED_IP, "s3cr3t") is True
    assert auth.authenticate(OTHER_ALLOWED_IP, "s3cr3t") is True


def test_an_added_address_still_needs_the_secret() -> None:
    """Widening the allowlist widens authentication; it does not bypass it."""
    auth = SourceIpAndSecretAuth.from_settings(_settings(extra=["127.0.0.1"]))

    assert auth.authenticate("127.0.0.1", "wrong") is False
    assert auth.authenticate("127.0.0.1", None) is False


def test_an_added_address_cannot_rescue_an_unconfigured_secret() -> None:
    """An empty configured secret makes the comparison vacuous, so it fails
    closed no matter where the request came from."""
    auth = SourceIpAndSecretAuth.from_settings(
        _settings(secret="", extra=["127.0.0.1"])
    )

    assert auth.authenticate("127.0.0.1", "") is False
