"""Webhook authentication: source-IP allowlist AND shared secret.

TradingView cannot sign its requests (no HMAC, no headers it controls), so
this pair is the entire authentication story for the public webhook
(spec: signal-ingress § Webhook Authentication).

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
"""

from strategy_manager.shared.config import TRADINGVIEW_SOURCE_IPS, Settings


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
        return provided_secret == self._expected_secret
