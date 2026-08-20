"""Exchange API credentials as domain objects.

Two types on purpose. ``ExchangeCredential`` carries the real secret and
exists only between the vault decrypting it and the signer using it.
``CredentialHint`` is what everything else is allowed to see.

Keeping them apart makes the safe thing the easy thing: an endpoint or a log
line that reaches for a credential gets the hint, because the type carrying
the secret never leaves the worker's signing path (CLAUDE.md rule 8).
"""

from dataclasses import dataclass

from strategy_manager.shared.domain.errors import InvariantViolation

LAST4_LENGTH = 4


@dataclass(frozen=True, slots=True, repr=False)
class ExchangeCredential:
    """A decrypted API key pair. Never persist, serialize or log this."""

    exchange: str
    label: str
    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if not self.api_key:
            raise InvariantViolation("ExchangeCredential.api_key must not be empty")
        if not self.api_secret:
            raise InvariantViolation("ExchangeCredential.api_secret must not be empty")
        if len(self.api_key) < LAST4_LENGTH:
            raise InvariantViolation(
                f"ExchangeCredential.api_key must be at least {LAST4_LENGTH} characters"
            )

    @property
    def last4(self) -> str:
        return self.api_key[-LAST4_LENGTH:]

    def hint(self) -> "CredentialHint":
        return CredentialHint(
            exchange=self.exchange, label=self.label, api_key_last4=self.last4
        )

    def __repr__(self) -> str:
        """Redacted. A default dataclass repr would put both secrets into
        every traceback that touches this object."""
        return (
            f"ExchangeCredential(exchange={self.exchange!r}, label={self.label!r}, "
            f"api_key='***{self.last4}', api_secret='***')"
        )


@dataclass(frozen=True, slots=True)
class CredentialHint:
    """The most a client may ever learn about a stored credential."""

    exchange: str
    label: str
    api_key_last4: str
