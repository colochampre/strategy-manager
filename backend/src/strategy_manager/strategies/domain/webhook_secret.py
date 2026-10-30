"""A strategy's webhook secret: generated here, stored only as a hash.

Multi-user design AD6. The plain secret exists in exactly two places: the
response that creates or regenerates it, and the TradingView alert the owner pastes
it into. The database holds its SHA-256 hex, which is also what ingress compares
(``signals/infrastructure/auth.py``), so the two must agree on the digest.
"""

import hashlib
import secrets


def new_webhook_secret() -> str:
    """32 random bytes, URL-safe, so it can ride in the alert's query string."""
    return secrets.token_urlsafe(32)


def hash_webhook_secret(secret: str) -> str:
    """The SHA-256 hex of the secret's UTF-8 bytes: the value stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
