"""Exchange API credentials as domain objects.

Two types on purpose. ``ExchangeCredential`` carries the real secret and
exists only between the vault decrypting it and the signer using it.
``CredentialHint`` is what everything else is allowed to see.

Keeping them apart makes the safe thing the easy thing: an endpoint or a log
line that reaches for a credential gets the hint, because the type carrying
the secret never leaves the worker's signing path (CLAUDE.md rule 8).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from strategy_manager.shared.domain.errors import InvariantViolation

LAST4_LENGTH = 4


class FactSource(StrEnum):
    """Who established a recorded fact about a key.

    The record says how each fact was established and never claims more than
    was: ``VERIFIED`` means the venue said so, ``OWNER_CONFIRMED`` means the
    owner said so, ``UNRECORDED`` means no record exists (a row sealed before
    the facts were kept). The values are stored verbatim, so they are spelled
    exactly as the database CHECK spells them.
    """

    VERIFIED = "VERIFIED"
    OWNER_CONFIRMED = "OWNER_CONFIRMED"
    UNRECORDED = "UNRECORDED"


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

    def hint(self, facts: "KeyFacts") -> "CredentialHint":
        return CredentialHint(
            exchange=self.exchange, label=self.label, api_key_last4=self.last4, facts=facts
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
    """The most a client may ever learn about a stored credential: its last
    four characters and the facts recorded about it. No secret, no ciphertext,
    no raw permission payload."""

    exchange: str
    label: str
    api_key_last4: str
    facts: "KeyFacts"


@dataclass(frozen=True, slots=True)
class KeyFacts:
    """What is recorded about a key, and how each fact was established.

    Deliberately not part of ``ExchangeCredential``: the object that carries the
    secret should not also carry the record about it. No field has a default,
    so a caller states every one; the only named constructor is ``unrecorded``.

    ``__post_init__`` refuses the states database constraints 2 to 4 refuse
    (``ck_exchange_credentials_*``), so the domain and the table agree on what
    cannot exist. Constraints 5 and 6 also need the exchange, which lives on the
    row and not here; the table enforces those alone.
    """

    trade_capable: bool
    trade_capability_source: FactSource
    trade_confirmed_at: datetime | None
    withdraw_check: FactSource
    withdraw_confirmed_at: datetime | None
    validated_at: datetime | None
    internal_transfer: bool | None

    def __post_init__(self) -> None:
        for label, source in (
            ("trade capability", self.trade_capability_source),
            ("withdraw check", self.withdraw_check),
        ):
            if not isinstance(source, FactSource):
                raise InvariantViolation(
                    f"KeyFacts {label} source must be a FactSource, got {source!r}"
                )

        # Constraint 2: a confirmation and its timestamp exist together.
        for label, source, confirmed_at in (
            ("trade", self.trade_capability_source, self.trade_confirmed_at),
            ("withdraw", self.withdraw_check, self.withdraw_confirmed_at),
        ):
            confirmed = source is FactSource.OWNER_CONFIRMED
            if confirmed != (confirmed_at is not None):
                raise InvariantViolation(
                    f"KeyFacts {label}: an OWNER_CONFIRMED source and its confirmation "
                    "timestamp must exist together"
                )

        # Constraint 3: the owner confirms a capability, never an incapability.
        if self.trade_capability_source is FactSource.OWNER_CONFIRMED and not self.trade_capable:
            raise InvariantViolation(
                "KeyFacts: the owner confirms a capability; an OWNER_CONFIRMED "
                "incapability cannot be recorded"
            )

        # Constraint 4: a row is either fully recorded or fully legacy.
        trade_legacy = self.trade_capability_source is FactSource.UNRECORDED
        withdraw_legacy = self.withdraw_check is FactSource.UNRECORDED
        if trade_legacy != withdraw_legacy:
            raise InvariantViolation(
                "KeyFacts: trade capability and withdraw check must both be recorded "
                "or both be UNRECORDED"
            )
        if (self.validated_at is None) != withdraw_legacy:
            raise InvariantViolation(
                "KeyFacts: validated_at is set exactly when the facts are recorded"
            )

    @classmethod
    def unrecorded(cls, *, trade_capable: bool) -> "KeyFacts":
        """A key with no record of how it was checked: sealed before facts were
        kept, or sealed by a path that makes no claim (Pionex)."""
        return cls(
            trade_capable=trade_capable,
            trade_capability_source=FactSource.UNRECORDED,
            trade_confirmed_at=None,
            withdraw_check=FactSource.UNRECORDED,
            withdraw_confirmed_at=None,
            validated_at=None,
            internal_transfer=None,
        )
