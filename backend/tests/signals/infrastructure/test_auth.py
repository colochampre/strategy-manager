"""Unit tests for the webhook's two authentication halves: ``SourceIpAuth`` (the
global source address) and ``secret_matches_hash`` (the strategy's own secret).

Covers spec: signal-ingress § Webhook Authentication; multi-user design AD6.
"""

from strategy_manager.shared.config import Settings
from strategy_manager.signals.infrastructure.auth import (
    SourceIpAuth,
    resolve_source_ip,
    secret_matches_hash,
)
from tests.owner import secret_hash

ALLOWED_IP = "52.89.214.238"
OTHER_ALLOWED_IP = "34.212.75.30"


def _settings(
    extra: list[str] | None = None,
    behind_tunnel: bool = False,
) -> Settings:
    """Built without reading .env, so these assertions describe the code and
    not whatever the developer's machine happens to be configured with."""
    return Settings(
        extra_webhook_source_ips=extra or [],
        behind_cloudflare_tunnel=behind_tunnel,
        _env_file=None,  # type: ignore[call-arg]
    )


def test_a_documented_ip_is_allowed() -> None:
    assert SourceIpAuth().allows(ALLOWED_IP) is True


def test_an_unknown_ip_is_refused() -> None:
    assert SourceIpAuth().allows("203.0.113.9") is False


def test_only_the_four_documented_ips_are_allowed() -> None:
    auth = SourceIpAuth()

    assert auth.allows(OTHER_ALLOWED_IP) is True
    assert auth.allows(None) is False


def test_by_default_only_tradingviews_addresses_are_accepted() -> None:
    """The extra list is empty unless a deployment sets it, so configuring
    nothing behaves exactly as before."""
    auth = SourceIpAuth.from_settings(_settings())

    assert auth.allows(ALLOWED_IP) is True
    assert auth.allows("127.0.0.1") is False


def test_a_configured_address_is_accepted_alongside_tradingviews() -> None:
    """Without this the ingress path cannot be rehearsed at all: an alert has
    to come from one of four fixed addresses, so nobody can send themselves a
    test one."""
    auth = SourceIpAuth.from_settings(_settings(extra=["127.0.0.1"]))

    assert auth.allows("127.0.0.1") is True


def test_configuration_can_only_widen_never_replace() -> None:
    """No configuration may stop TradingView's own alerts from arriving, which
    is the one thing this endpoint exists for."""
    auth = SourceIpAuth.from_settings(_settings(extra=["127.0.0.1"]))

    assert auth.allows(ALLOWED_IP) is True
    assert auth.allows(OTHER_ALLOWED_IP) is True


# --- secret_matches_hash: the strategy's own secret ------------------------


def test_the_secret_whose_hash_is_stored_matches() -> None:
    assert secret_matches_hash("s3cr3t", secret_hash("s3cr3t")) is True


def test_another_secret_does_not_match() -> None:
    assert secret_matches_hash("wrong", secret_hash("s3cr3t")) is False


def test_a_missing_or_empty_secret_does_not_match() -> None:
    stored = secret_hash("s3cr3t")

    assert secret_matches_hash(None, stored) is False
    assert secret_matches_hash("", stored) is False


def test_a_strategy_with_no_stored_hash_matches_nothing() -> None:
    """Not even the empty secret, whose hash is a well-known constant."""
    assert secret_matches_hash("s3cr3t", None) is False
    assert secret_matches_hash("", None) is False
    assert secret_matches_hash("s3cr3t", "") is False


def test_the_hash_itself_is_not_a_secret_that_matches() -> None:
    """A leaked hash must not open the webhook: the comparison hashes what the
    caller sends, so sending the stored value hashes it a second time."""
    stored = secret_hash("s3cr3t")

    assert secret_matches_hash(stored, stored) is False


def test_a_non_ascii_secret_is_compared_without_raising() -> None:
    """``hmac.compare_digest`` rejects non-ASCII ``str``; the comparison works on
    bytes, so a unicode secret fails as wrong rather than as a 500, and matches
    when it is the one stored."""
    assert secret_matches_hash("contraseña", secret_hash("s3cr3t")) is False
    assert secret_matches_hash("contraseña", secret_hash("contraseña")) is True


# --- resolve_source_ip: which address the allowlist is given ----------------
#
# Behind a Cloudflare Tunnel the peer address is cloudflared's, so reading it
# would 401 every genuine alert. The interesting cases are the refusals.

CLOUDFLARED_PEER = "127.0.0.1"


def test_exposed_directly_the_peer_address_is_the_clients() -> None:
    resolved = resolve_source_ip(
        peer_ip=ALLOWED_IP,
        forwarded_ip=None,
        behind_cloudflare_tunnel=False,
    )

    assert resolved == ALLOWED_IP


def test_exposed_directly_the_header_is_ignored_entirely() -> None:
    """Not a preference and not a fallback: ignored. Otherwise anyone reaching
    the port directly could name their own source address."""
    resolved = resolve_source_ip(
        peer_ip="203.0.113.9",
        forwarded_ip=ALLOWED_IP,
        behind_cloudflare_tunnel=False,
    )

    assert resolved == "203.0.113.9"


def test_behind_the_tunnel_the_forwarded_address_is_the_clients() -> None:
    resolved = resolve_source_ip(
        peer_ip=CLOUDFLARED_PEER,
        forwarded_ip=ALLOWED_IP,
        behind_cloudflare_tunnel=True,
    )

    assert resolved == ALLOWED_IP


def test_behind_the_tunnel_a_missing_header_never_falls_back_to_the_peer() -> None:
    """The peer is the loopback. A deployment that allowlisted the loopback to
    rehearse would otherwise have opened the allowlist to every direct caller
    willing to omit the header."""
    resolved = resolve_source_ip(
        peer_ip=CLOUDFLARED_PEER,
        forwarded_ip=None,
        behind_cloudflare_tunnel=True,
    )

    assert resolved is None
    assert (
        SourceIpAuth.from_settings(
            _settings(extra=[CLOUDFLARED_PEER], behind_tunnel=True)
        ).allows(resolved)
        is False
    )


def test_behind_the_tunnel_a_forwarded_list_is_refused() -> None:
    """A comma-separated value is X-Forwarded-For's shape, so something other
    than Cloudflare wrote it. There is no safe entry to pick."""
    resolved = resolve_source_ip(
        peer_ip=CLOUDFLARED_PEER,
        forwarded_ip=f"203.0.113.9, {ALLOWED_IP}",
        behind_cloudflare_tunnel=True,
    )

    assert resolved is None


def test_behind_the_tunnel_a_blank_header_is_refused() -> None:
    resolved = resolve_source_ip(
        peer_ip=CLOUDFLARED_PEER,
        forwarded_ip="   ",
        behind_cloudflare_tunnel=True,
    )

    assert resolved is None


def test_behind_the_tunnel_surrounding_whitespace_is_tolerated() -> None:
    resolved = resolve_source_ip(
        peer_ip=CLOUDFLARED_PEER,
        forwarded_ip=f"  {ALLOWED_IP}  ",
        behind_cloudflare_tunnel=True,
    )

    assert resolved == ALLOWED_IP
