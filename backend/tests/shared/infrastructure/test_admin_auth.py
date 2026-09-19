"""Unit tests for AdminTokenAuth — the shared bearer check guarding every
admin surface (``/strategies``, ``/reconciliation``).

The first surface it protects writes no orders, so the thing these assertions
defend is one step removed: a caller who can register a strategy, arm it and
set its allocation to 100% has decided what the worker trades with the pool.
"""

from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.admin_auth import AdminTokenAuth

TOKEN = "adm1n-t0ken"


def _settings(token: str = TOKEN) -> Settings:
    """Built without reading .env, so these assertions describe the code and
    not whatever the developer's machine happens to be configured with."""
    return Settings(
        admin_api_token=token,
        _env_file=None,  # type: ignore[call-arg]
    )


def test_a_correct_bearer_token_authenticates() -> None:
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate(f"Bearer {TOKEN}") is True


def test_the_scheme_is_matched_case_insensitively() -> None:
    """RFC 7235 makes it case-insensitive, and clients genuinely differ."""
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate(f"bearer {TOKEN}") is True


def test_a_wrong_token_is_rejected() -> None:
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate("Bearer nope") is False


def test_a_missing_header_is_rejected() -> None:
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate(None) is False


def test_a_header_without_the_bearer_scheme_is_rejected() -> None:
    """The bare token is the shape a caller reaches for first, and accepting
    it would mean the scheme is decoration rather than part of the contract."""
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate(TOKEN) is False


def test_another_scheme_carrying_the_right_token_is_rejected() -> None:
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate(f"Basic {TOKEN}") is False


def test_the_scheme_alone_is_rejected() -> None:
    auth = AdminTokenAuth(expected_token=TOKEN)

    assert auth.authenticate("Bearer") is False
    assert auth.authenticate("Bearer ") is False


def test_an_unconfigured_expected_token_never_authenticates() -> None:
    """The failure mode this exists for: the caller supplies the other side of
    the comparison, so an empty expected token would MATCH a request sending
    an empty one — an unconfigured deployment authenticating the internet."""
    auth = AdminTokenAuth(expected_token="")

    assert auth.authenticate("Bearer ") is False
    assert auth.authenticate("Bearer anything") is False
    assert auth.authenticate(None) is False


def test_the_token_is_read_from_settings() -> None:
    auth = AdminTokenAuth.from_settings(_settings())

    assert auth.authenticate(f"Bearer {TOKEN}") is True


def test_settings_without_a_token_still_never_authenticate() -> None:
    """``from_settings`` is no escape hatch around the empty-token rule: the
    default value of the setting is exactly the dangerous one."""
    auth = AdminTokenAuth.from_settings(_settings(token=""))

    assert auth.authenticate("Bearer ") is False
