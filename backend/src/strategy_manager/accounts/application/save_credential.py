"""``SaveCredential``: the one way an exchange key enters the vault.

The steps run in this order, and the order is the safety property:

1. ``check_confirmations``, BEFORE any venue call. A Binance key missing a
   confirmation, or a Bybit key carrying one, is refused and nothing is sent to
   the venue: a key that cannot be stored is not worth a signed request.
2. Inspect: the live read (rule 8a) plus the permission snapshot. A rejected key
   and an unreachable venue are different outcomes on purpose: the first is the
   owner's to fix, the second is worth retrying by hand.
3. ``evaluate_key``: pure policy over what the venue said and what the owner
   confirmed.
4. Store with supersede. ``validated_at`` and each confirmation's timestamp are
   stamped from the clock in ONE reading, so they are the same instant and
   ``evaluate_key`` stays pure. A rotation deactivates the previous row and
   keeps it; nothing about the previous key is inherited.
5. Commit.

The result is typed. ``Saved`` carries the last four characters and the facts
recorded; ``SaveRefused`` carries the outcome, a detail that names tokens or
fields (never a payload or a secret) and, for a missing confirmation, which.

Nothing here decrypts: ``CredentialWriterPort`` has no ``load`` (rule 8).

Logging asks "what fails here without a single log line?". A refusal is one
WARNING naming the exchange and the outcome. An unreachable venue is a WARNING
too, not an ERROR: it is a save attempt the owner retries by hand, and nothing
was stored. A save is one INFO with the exchange and the last four characters.
No line ever carries a key, a secret or a venue payload.
"""

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from strategy_manager.accounts.application.ports import (
    CommitPort,
    CredentialWriterPort,
    KeyInspectorRegistryPort,
)
from strategy_manager.accounts.domain.errors import (
    ConcurrentCredentialSave,
    KeyRejected,
    VenueUnreachable,
)
from strategy_manager.accounts.domain.exchange_credential import (
    ExchangeCredential,
    FactSource,
    KeyFacts,
)
from strategy_manager.accounts.domain.key_policy import (
    KeyAccepted,
    KeyRefused,
    OwnerConfirmations,
    check_confirmations,
    evaluate_key,
)
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


class SaveOutcome(StrEnum):
    SAVED = "SAVED"
    KEY_REJECTED = "KEY_REJECTED"
    VENUE_UNREACHABLE = "VENUE_UNREACHABLE"
    WITHDRAW_PERMISSION = "WITHDRAW_PERMISSION"
    PERMISSIONS_UNAVAILABLE = "PERMISSIONS_UNAVAILABLE"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_NOT_APPLICABLE = "CONFIRMATION_NOT_APPLICABLE"
    CONCURRENT_SAVE = "CONCURRENT_SAVE"


@dataclass(frozen=True, slots=True)
class Saved:
    """The key is stored and active. ``warnings`` is ``("READ_ONLY_KEY",)`` for
    a read-only Bybit key (decision 18); "not verified" is state, not a warning."""

    last4: str
    facts: KeyFacts
    warnings: tuple[str, ...]
    outcome: SaveOutcome = field(default=SaveOutcome.SAVED, init=False)


@dataclass(frozen=True, slots=True)
class SaveRefused:
    """Nothing was stored. ``detail`` names tokens or fields, never a payload;
    ``missing`` names the absent confirmations for ``CONFIRMATION_REQUIRED``."""

    outcome: SaveOutcome
    detail: str
    missing: tuple[str, ...] = ()


SaveResult = Saved | SaveRefused


class SaveCredential:
    def __init__(
        self,
        inspectors: KeyInspectorRegistryPort,
        writer: CredentialWriterPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._inspectors = inspectors
        self._writer = writer
        self._commit = commit
        self._clock = clock

    async def execute(
        self, credential: ExchangeCredential, confirmations: OwnerConfirmations
    ) -> SaveResult:
        exchange = credential.exchange

        premature = check_confirmations(exchange, confirmations)
        if premature is not None:
            return self._refused(exchange, premature)

        try:
            snapshot = await self._inspectors.for_exchange(exchange).inspect(credential)
        except KeyRejected as exc:
            return self._refused_with(exchange, SaveOutcome.KEY_REJECTED, str(exc))
        except VenueUnreachable as exc:
            return self._refused_with(exchange, SaveOutcome.VENUE_UNREACHABLE, str(exc))

        verdict = evaluate_key(exchange, snapshot, confirmations)
        if isinstance(verdict, KeyRefused):
            return self._refused(exchange, verdict)

        facts = self._stamp(verdict)
        try:
            await self._writer.store(credential, facts)
        except ConcurrentCredentialSave as exc:
            return self._refused_with(exchange, SaveOutcome.CONCURRENT_SAVE, str(exc))
        await self._commit.commit()

        logger.info("saved %s credential (key ending %s)", exchange, credential.last4)
        return Saved(last4=credential.last4, facts=facts, warnings=verdict.warnings)

    def _stamp(self, verdict: KeyAccepted) -> KeyFacts:
        """One clock reading for every timestamp: they are the same instant."""
        now = self._clock.now()
        return KeyFacts(
            trade_capable=verdict.trade_capable,
            trade_capability_source=verdict.trade_capability_source,
            trade_confirmed_at=(
                now if verdict.trade_capability_source is FactSource.OWNER_CONFIRMED else None
            ),
            withdraw_check=verdict.withdraw_check,
            withdraw_confirmed_at=(
                now if verdict.withdraw_check is FactSource.OWNER_CONFIRMED else None
            ),
            validated_at=now,
            internal_transfer=verdict.internal_transfer,
        )

    def _refused(self, exchange: str, refusal: KeyRefused) -> SaveRefused:
        outcome = SaveOutcome(refusal.outcome.value)
        logger.warning("refused to save %s credential: %s", exchange, outcome.value)
        return SaveRefused(outcome, refusal.detail, refusal.missing)

    def _refused_with(self, exchange: str, outcome: SaveOutcome, detail: str) -> SaveRefused:
        logger.warning("refused to save %s credential: %s", exchange, outcome.value)
        return SaveRefused(outcome, detail)
