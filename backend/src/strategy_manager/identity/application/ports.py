"""Ports of the identity module (multi-user design AD1)."""

from collections.abc import Sequence
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
