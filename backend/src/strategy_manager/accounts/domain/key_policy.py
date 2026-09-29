"""What a venue key must be, before it is stored.

Pure domain: no framework, no I/O. The save use case reads the venue through a
``KeyInspector`` (which raises ``KeyRejected`` or ``VenueUnreachable`` for rule
8a, the live read) and hands this module what the venue said plus what the
owner confirmed. This module only ever sees a key the venue already accepted.

**Verified inputs and confirmed inputs never mix.** ``PermissionSnapshot``
holds only what the venue said. ``OwnerConfirmations`` holds only what the
owner said. Bybit is verified server-side, so a Bybit confirmation is refused
rather than dropped; Binance cannot be inspected for either fact, so its
snapshot is empty and its facts are owner-confirmed (decisions 24 and 30).

**``canTrade`` and ``canWithdraw`` appear nowhere.** Binance reports them at
the ACCOUNT level, and probe P6 found both true on a key that could neither
trade futures nor withdraw. Reading them would record a false "verified".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from strategy_manager.accounts.domain.exchange_credential import FactSource
from strategy_manager.shared.domain.errors import InvariantViolation

WITHDRAWALS_CONFIRMATION = "withdrawals_disabled_confirmed"
FUTURES_CONFIRMATION = "futures_enabled_confirmed"

READ_ONLY_WARNING = "READ_ONLY_KEY"

INTERNAL_TRANSFER_TOKEN = "AccountTransfer"
# Bybit ``permissions.Wallet`` tokens that move money between the owner's own
# accounts and cannot take it off the platform. Anything else is refused.
TRANSFER_ALLOWLIST = frozenset({INTERNAL_TRANSFER_TOKEN, "SubMemberTransfer"})


class PolicyBasis(StrEnum):
    """How a venue's key facts are established."""

    SERVER_VERIFIED = "SERVER_VERIFIED"
    OWNER_CONFIRMED = "OWNER_CONFIRMED"


class RefusalOutcome(StrEnum):
    WITHDRAW_PERMISSION = "WITHDRAW_PERMISSION"
    PERMISSIONS_UNAVAILABLE = "PERMISSIONS_UNAVAILABLE"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_NOT_APPLICABLE = "CONFIRMATION_NOT_APPLICABLE"


KEY_POLICIES: Mapping[str, PolicyBasis] = {
    "bybit": PolicyBasis.SERVER_VERIFIED,
    "binance": PolicyBasis.OWNER_CONFIRMED,
}


class UnservedExchange(InvariantViolation):
    """No key policy exists for this exchange. There is no fallback: a default
    policy is the failure being prevented."""


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    """Only what the venue said about a key. ``None`` means the venue did not
    say (or said it in a shape that cannot be trusted), never "no".

    Both are ``None`` for Binance, whose inspector cannot observe them.
    """

    wallet_permissions: frozenset[str] | None = None
    read_only: bool | None = None


@dataclass(frozen=True, slots=True)
class OwnerConfirmations:
    """Only what the owner said."""

    withdrawals_disabled: bool = False
    futures_enabled: bool = False


@dataclass(frozen=True, slots=True)
class KeyAccepted:
    """A key that may be stored, and the facts to store with it.

    No timestamps: the save use case stamps them from its clock, so this
    module stays pure.
    """

    trade_capable: bool
    trade_capability_source: FactSource
    withdraw_check: FactSource
    internal_transfer: bool | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KeyRefused:
    """A key that must not be stored. ``detail`` names tokens or fields, never
    a payload."""

    outcome: RefusalOutcome
    detail: str
    missing: tuple[str, ...] = ()


KeyVerdict = KeyAccepted | KeyRefused


def policy_for(exchange: str) -> PolicyBasis:
    try:
        return KEY_POLICIES[exchange]
    except KeyError:
        raise UnservedExchange(
            f"no key policy is defined for exchange {exchange!r}; add one to "
            "KEY_POLICIES rather than falling back to another venue's rules"
        ) from None


def check_confirmations(exchange: str, confirmations: OwnerConfirmations) -> KeyRefused | None:
    """The owner's statements, judged before any venue is called.

    Binance needs both, because nothing reachable reveals either fact. Bybit
    is verified server-side, so a true confirmation there is refused: it would
    otherwise be dropped silently and leave the owner believing it was kept.
    Nothing is sent to a venue for a key that cannot be stored.
    """
    if policy_for(exchange) is PolicyBasis.OWNER_CONFIRMED:
        missing = tuple(
            name
            for name, given in (
                (WITHDRAWALS_CONFIRMATION, confirmations.withdrawals_disabled),
                (FUTURES_CONFIRMATION, confirmations.futures_enabled),
            )
            if not given
        )
        if missing:
            return KeyRefused(
                RefusalOutcome.CONFIRMATION_REQUIRED,
                f"{exchange} cannot be checked by this panel; confirm: {', '.join(missing)}",
                missing,
            )
        return None

    offered = tuple(
        name
        for name, given in (
            (WITHDRAWALS_CONFIRMATION, confirmations.withdrawals_disabled),
            (FUTURES_CONFIRMATION, confirmations.futures_enabled),
        )
        if given
    )
    if offered:
        return KeyRefused(
            RefusalOutcome.CONFIRMATION_NOT_APPLICABLE,
            f"{exchange} is verified by the venue and takes no owner confirmation: "
            f"{', '.join(offered)}",
        )
    return None


def evaluate_key(
    exchange: str, snapshot: PermissionSnapshot, confirmations: OwnerConfirmations
) -> KeyVerdict:
    """Judges a key the venue already accepted (rule 8a is the inspector's).

    Pure: the same inputs give the same verdict, and it stamps nothing.
    """
    refusal = check_confirmations(exchange, confirmations)
    if refusal is not None:
        return refusal

    if policy_for(exchange) is PolicyBasis.OWNER_CONFIRMED:
        return _confirmed(exchange, snapshot)
    return _verified(snapshot)


def _confirmed(exchange: str, snapshot: PermissionSnapshot) -> KeyAccepted:
    if snapshot != PermissionSnapshot():
        raise InvariantViolation(
            f"{exchange} facts are owner-confirmed, so its snapshot must be empty; a "
            "non-empty one means a verified input reached the confirmed branch"
        )
    return KeyAccepted(
        trade_capable=True,
        trade_capability_source=FactSource.OWNER_CONFIRMED,
        withdraw_check=FactSource.OWNER_CONFIRMED,
        internal_transfer=None,
        warnings=(),
    )


def _verified(snapshot: PermissionSnapshot) -> KeyVerdict:
    wallet = snapshot.wallet_permissions
    if wallet is None:
        return KeyRefused(
            RefusalOutcome.PERMISSIONS_UNAVAILABLE,
            "the venue did not report the key's wallet permissions",
        )

    offending = sorted(wallet - TRANSFER_ALLOWLIST)
    if offending:
        return KeyRefused(
            RefusalOutcome.WITHDRAW_PERMISSION,
            f"the key carries wallet permissions outside the transfer allowlist: "
            f"{', '.join(offending)}",
        )

    if snapshot.read_only is None:
        return KeyRefused(
            RefusalOutcome.PERMISSIONS_UNAVAILABLE,
            "the venue did not report whether the key is read-only",
        )

    return KeyAccepted(
        trade_capable=not snapshot.read_only,
        trade_capability_source=FactSource.VERIFIED,
        withdraw_check=FactSource.VERIFIED,
        internal_transfer=INTERNAL_TRANSFER_TOKEN in wallet,
        warnings=(READ_ONLY_WARNING,) if snapshot.read_only else (),
    )
