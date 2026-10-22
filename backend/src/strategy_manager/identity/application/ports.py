"""Ports of the identity module (multi-user design AD1)."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.identity.domain.user import User


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
