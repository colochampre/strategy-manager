"""Ports (Protocols) owned by ``shared`` and consumed by every module.

Consumer declares the port, provider owns the adapter — the composition root
(``main.py``) is the only place that binds them together.
"""

from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.application.job import ClaimedJob, Job
from strategy_manager.shared.domain.money import Currency


class ClockPort(Protocol):
    """The single source of "now" for every application-layer use case."""

    def now(self) -> datetime: ...


class UsdRateProviderPort(Protocol):
    """USD conversion rate for a settlement currency, at the time of a fill."""

    async def usd_rate(self, currency: Currency) -> Decimal: ...


class JobQueuePort(Protocol):
    """PostgreSQL-backed job queue: enqueue, claim, ack, fail-and-retry."""

    async def enqueue(self, job: Job) -> UUID: ...
    async def claim(self) -> ClaimedJob | None: ...
    async def ack(self, job_id: UUID) -> None: ...
    async def fail(self, job_id: UUID, error: str) -> None: ...


class JobRetentionPort(Protocol):
    """Removal of finished job rows, kept deliberately OUT of ``JobQueuePort``.

    That port is the claim/ack/fail contract every worker path depends on, and
    every fake in the test suite implements it; widening it to carry a
    maintenance concern would make retention something each of those fakes has
    to answer for. Retention has one caller and one adapter, so it gets its own
    port instead.

    One call deletes at most ``limit`` rows and returns how many it actually
    deleted, which is what lets the caller batch and stop.
    """

    async def delete_done_before(self, cutoff: datetime, limit: int) -> int: ...


class CommitPort(Protocol):
    """Mirrors every module's narrow ``CommitPort`` — deliberately small so any
    object with an async ``commit()`` (including a raw ``AsyncSession``)
    satisfies it structurally, without leaking SQLAlchemy into this layer."""

    async def commit(self) -> None: ...


class UnitOfWorkPort(Protocol):
    """An async-context-managed transaction boundary."""

    async def __aenter__(self) -> "UnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
