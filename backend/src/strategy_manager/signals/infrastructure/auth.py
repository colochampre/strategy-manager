"""Webhook authentication: source-IP allowlist AND shared secret.

TradingView cannot sign its requests — it controls the URL and the alert body
and nothing else, with no headers of its own (re-verified against TradingView's
webhook documentation, 2026-08-28) — so this pair is the entire authentication
story for the public webhook (spec: signal-ingress § Webhook Authentication).

**BOTH, never either.** The secret alone would be a bearer token travelling in
a query string, which ends up in logs and browser history. The address alone
would trust anyone who can reach the port from the right network. Requiring
both means a leaked secret is useless from the wrong address and a spoofed
address is useless without the secret.

The allowlist can be widened by configuration (``EXTRA_WEBHOOK_SOURCE_IPS``)
because otherwise the ingress path cannot be rehearsed at all — the alert has
to originate from one of four fixed addresses, so nobody can send themselves a
test one. Widening it is widening authentication, which is why it is empty by
default and why this module reads the addresses rather than deciding them.

Behind a Cloudflare Tunnel the peer address is no longer TradingView's: it is
cloudflared's, reaching this application over the loopback. The originating
address arrives in ``CF-Connecting-IP``, which Cloudflare overwrites on every
request it forwards, so no client can forge it. That header is worth trusting
only because the tunnel is the sole route to this origin — nothing else can
reach the port to send a header of its own. Which is exactly why trusting it
is a deployment declaration (``BEHIND_CLOUDFLARE_TUNNEL``) and never an
autodetection: a trusted header that switches itself on switches on precisely
for the requests that did not come through the tunnel.
"""

import hmac

from strategy_manager.shared.config import TRADINGVIEW_SOURCE_IPS, Settings

#: Cloudflare overwrites this on every request it forwards to the origin.
CLOUDFLARE_CLIENT_IP_HEADER = "CF-Connecting-IP"


def resolve_source_ip(
    *,
    peer_ip: str | None,
    forwarded_ip: str | None,
    behind_cloudflare_tunnel: bool,
) -> str | None:
    """The address the allowlist must judge, given how this is deployed.

    Exposed directly, the peer address IS the client's. Behind the tunnel it is
    cloudflared's, and the client's is in ``CF-Connecting-IP``.

    Two refusals matter more here than the happy path:

    - Not behind the tunnel, the header is ignored outright — never preferred,
      never a fallback. Otherwise anyone reaching the port directly could name
      their own source address and the allowlist would constrain nothing.
    - Behind the tunnel, a missing header yields ``None``, which no allowlist
      contains. It does NOT fall back to the peer address, because that address
      is the loopback: a deployment that added the loopback to
      ``EXTRA_WEBHOOK_SOURCE_IPS`` to rehearse would otherwise have handed
      every direct caller a way past the allowlist.
    """

    if not behind_cloudflare_tunnel:
        return peer_ip
    if forwarded_ip is None:
        return None
    candidate = forwarded_ip.strip()
    # Cloudflare sends exactly one address. A comma-separated list is
    # X-Forwarded-For's shape, which means something other than Cloudflare
    # wrote this header — and there is no safe way to choose an entry, so
    # choose none.
    if not candidate or "," in candidate:
        return None
    return candidate


class SourceIpAndSecretAuth:
    """Authenticates a webhook request by BOTH source IP AND shared secret."""

    def __init__(
        self,
        expected_secret: str,
        allowed_ips: frozenset[str] = TRADINGVIEW_SOURCE_IPS,
    ) -> None:
        self._expected_secret = expected_secret
        self._allowed_ips = allowed_ips

    @classmethod
    def from_settings(cls, settings: Settings) -> "SourceIpAndSecretAuth":
        """TradingView's four addresses, plus whatever the deployment adds.

        A union rather than a replacement: no configuration can stop
        TradingView's own alerts from being accepted, which is the one thing
        this endpoint exists for.
        """
        return cls(
            expected_secret=settings.webhook_secret,
            allowed_ips=TRADINGVIEW_SOURCE_IPS
            | frozenset(settings.extra_webhook_source_ips),
        )

    def authenticate(self, source_ip: str | None, provided_secret: str | None) -> bool:
        if not self._expected_secret:
            # An empty configured secret would make comparison vacuous.
            # Startup invariant 3 (main.py) is supposed to prevent this in
            # production; fail closed here regardless.
            return False
        if source_ip not in self._allowed_ips:
            return False
        if provided_secret is None:
            return False
        # Constant-time. The margin an attacker could measure across a network
        # is small, but a variable-time comparison of a secret is not a thing
        # to knowingly leave in place.
        return hmac.compare_digest(
            provided_secret.encode("utf-8"), self._expected_secret.encode("utf-8")
        )
