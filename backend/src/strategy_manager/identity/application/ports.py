"""Ports of the identity module (multi-user design AD1)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.identity.domain.user import User
from strategy_manager.shared.domain.mode import Mode


class IdentityRefusedError(Exception):
    """The request carries no identity this deployment accepts: no assertion, a
    forged or expired one, one for another application, or one without an
    e-mail. The caller answers 401 and says nothing more (see
    ``identity/infrastructure/dependencies.py``)."""


class IdentityUnavailableError(Exception):
    """The identity could not be checked at all, for example because Access's
    signing keys could not be fetched. Not the caller's fault: the caller
    answers 503, never 401, so a Cloudflare outage never reads as a forged
    token."""


class DisplayNameTakenError(Exception):
    """Another user holds this name, ignoring case. It says nothing about who."""


class IdentityVerifierPort(Protocol):
    """Turns the request's Access assertion into the e-mail it vouches for.

    Raises ``IdentityRefusedError`` or ``IdentityUnavailableError``; returns the
    e-mail exactly as the assertion carries it, which ``normalize_email`` then
    folds."""

    async def verify(self, assertion: str | None) -> str: ...


class UserRepositoryPort(Protocol):
    async def find_or_create(self, email: str, now: datetime) -> User:
        """The user with this (already normal) e-mail, created with ``now`` as
        both timestamps when there is none. Two concurrent first requests for
        one address yield one row."""
        ...

    async def mark_seen(self, user_id: UUID, now: datetime) -> None: ...

    async def lock_for_mode_change(self, user_id: UUID) -> None:
        """Takes the user row ``FOR UPDATE``: it waits for an opening in flight,
        which holds that row ``FOR SHARE`` until its reservation commits, and holds
        back the next one until this transaction ends."""
        ...

    async def set_mode(self, user_id: UUID, mode: Mode) -> None: ...

    async def set_display_name(self, user_id: UUID, name: str) -> None:
        """Raises ``DisplayNameTakenError`` when another user holds ``name``."""
        ...


class TradeKeysPort(Protocol):
    async def holds_trade_capable_key(self, user_id: UUID) -> bool:
        """Whether ``user_id`` has an active trade-capable key on any exchange."""
        ...


class LiveExposurePort(Protocol):
    async def symbols(self, user_id: UUID) -> Sequence[str]:
        """Each market ``user_id`` holds something real on, once and in order:
        empty means nothing of theirs can still reach a venue."""
        ...


class CommitPort(Protocol):
    async def commit(self) -> None: ...


class SuspensionUsersPort(Protocol):
    async def lock_for_suspension(self, user_id: UUID) -> bool:
        """Takes the user row ``FOR UPDATE``, as a mode change does, and answers
        whether it is an account that exists and was not deleted."""
        ...

    async def suspend(self, user_id: UUID, now: datetime) -> None:
        """Sets ``suspended_at`` to ``now`` unless it is already set: suspending
        twice keeps the first date."""
        ...

    async def lift_suspension(self, user_id: UUID) -> None: ...


# --- Account deletion (openspec/changes/account-deletion) -------------------------


@dataclass(frozen=True, slots=True)
class LockedPool:
    """A capital pool whose advisory lock the deletion takes, read from the pool's
    own row: ``user_id`` is its owner, the deleting user or one of their
    subscribers."""

    pool_id: int
    user_id: UUID
    exchange: str
    venue: str
    currency: str


@dataclass(frozen=True, slots=True)
class AuthoredStrategy:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class HeldStrategy:
    """A strategy the user authors on which someone still holds something: an open
    position, a live reservation or an attempt in flight. ``symbols`` may be empty
    while a reservation's symbol is not known to the exposure read."""

    id: UUID
    name: str
    symbols: tuple[str, ...]


class AccountUsersPort(Protocol):
    async def lock_for_mode_change(self, user_id: UUID) -> None:
        """The user row ``FOR UPDATE``: an opening in flight holds it ``FOR SHARE``
        until its reservation commits, so this waits for it."""
        ...

    async def wipe(self, user_id: UUID, now: datetime) -> None:
        """The e-mail becomes ``deleted-<id>@invalid``, the display name and the
        identity given at sign-up go, and ``deleted_at`` is ``now``."""
        ...


class AccountPoolsPort(Protocol):
    async def pools(self, user_id: UUID) -> Sequence[LockedPool]:
        """Every capital pool of ``user_id``, enabled or not."""
        ...

    async def disable_all(self, user_id: UUID) -> int:
        """Disables every pool of ``user_id``; the number that were enabled."""
        ...


class AuthoredStrategiesPort(Protocol):
    async def authored(self, user_id: UUID) -> Sequence[AuthoredStrategy]:
        """Every strategy ``user_id`` authors, archived ones included, lowest id first."""
        ...

    async def subscriber_pools(self, strategy_id: UUID) -> Sequence[LockedPool]:
        """The pool of every live (ACTIVE or LEAVING) seat on the strategy."""
        ...

    async def lock(self, strategy_id: UUID) -> None:
        """The strategy row ``FOR UPDATE``: a seat inserted on it waits for this."""
        ...

    async def exposure(self, strategy_id: UUID) -> tuple[str, ...] | None:
        """``None`` when nobody holds anything on the strategy; otherwise the
        symbols held, possibly none known."""
        ...

    async def close(self, strategy_id: UUID, now: datetime) -> int:
        """Makes the strategy private, disables it, replaces its webhook secret
        with one nobody holds, archives it and ends every live seat on it; the
        number of seats ended."""
        ...


@dataclass(frozen=True, slots=True)
class OwnSeat:
    """A live seat of the user's on someone else's strategy."""

    id: UUID
    strategy_id: UUID
    leaving: bool


class OwnSeatsPort(Protocol):
    async def live(self, user_id: UUID) -> Sequence[OwnSeat]:
        """Every ACTIVE or LEAVING seat of ``user_id``, each row locked ``FOR UPDATE``."""
        ...

    async def holds_open(self, user_id: UUID, strategy_id: UUID) -> bool:
        """``Leave``'s question: a position, a reservation or an opening in flight of
        the user's on the strategy."""
        ...

    async def leave(self, user_id: UUID, seat_id: UUID, now: datetime) -> None:
        """ACTIVE to LEAVING: no new openings; it ends when the last fill closes."""
        ...

    async def end(self, user_id: UUID, seat_id: UUID, now: datetime) -> None: ...


class OwnPositionsPort(Protocol):
    async def open(self, user_id: UUID) -> Sequence[UUID]:
        """The allocations the user's ledger still holds, one id each."""
        ...

    async def request_close(self, user_id: UUID, allocation_id: UUID) -> bool:
        """Queues the close "Close now" queues; the worker sends it after the commit.
        ``False`` when nothing new was queued: a close of it is in flight, or a job for
        it is already waiting."""
        ...


class AccountCredentialsPort(Protocol):
    async def delete_all(self, user_id: UUID) -> int:
        """Deletes every key row of ``user_id``, ciphertext included; the number deleted."""
        ...


class AccountPoolLockPort(Protocol):
    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None: ...


class AccountClockPort(Protocol):
    def now(self) -> datetime: ...
