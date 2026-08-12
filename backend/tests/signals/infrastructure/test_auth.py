"""Unit tests for SourceIpAndSecretAuth.

Covers spec: signal-ingress § Webhook Authentication.
"""

from strategy_manager.signals.infrastructure.auth import SourceIpAndSecretAuth

ALLOWED_IP = "52.89.214.238"
OTHER_ALLOWED_IP = "34.212.75.30"


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
