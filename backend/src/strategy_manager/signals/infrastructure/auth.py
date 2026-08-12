"""Webhook authentication: source-IP allowlist AND shared secret.

TradingView cannot sign its requests (no HMAC, no headers it controls), so
this pair is the entire authentication story for the public webhook
(spec: signal-ingress § Webhook Authentication).
"""

from strategy_manager.shared.config import TRADINGVIEW_SOURCE_IPS


class SourceIpAndSecretAuth:
    """Authenticates a webhook request by BOTH source IP AND shared secret."""

    def __init__(
        self,
        expected_secret: str,
        allowed_ips: frozenset[str] = TRADINGVIEW_SOURCE_IPS,
    ) -> None:
        self._expected_secret = expected_secret
        self._allowed_ips = allowed_ips

    def authenticate(self, source_ip: str | None, provided_secret: str | None) -> bool:
        if not self._expected_secret:
            # An empty configured secret would make comparison vacuous.
            # Startup invariant 3 (main.py) is supposed to prevent this in
            # production; fail closed here regardless.
            return False
        if source_ip not in self._allowed_ips:
            return False
        return provided_secret == self._expected_secret
