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


class AlertPort(Protocol):
    """One operational message, delivered somewhere a human will actually see it.

    Deliberately the narrowest thing that solves the problem it exists for: a
    ``balance.sync`` chain died in production and stayed dead for three days
    because the log was the only signal. Two strings — a line short enough to
    read on a lock screen, and the detail behind it.

    It carries NO severity, NO structure and NO delivery guarantee, because an
    adapter that could express those would invite a caller to branch on them.
    An implementation MUST NOT raise: this is called from behind work that is
    already failing, and an alert that can fail a job turns one outage into
    two.
    """

    async def send(self, title: str, body: str) -> None: ...


class JobQueuePort(Protocol):
    """PostgreSQL-backed job queue: enqueue, claim, ack, fail-and-retry."""

    async def enqueue(self, job: Job) -> UUID: ...

    async def enqueue_unique(self, job: Job) -> tuple[UUID, bool]:
        """Like ``enqueue``, but idempotent on ``job.dedupe_key``: a second
        call with the same key returns the existing row's id and inserts
        nothing new (design.md § S5, the continuation's per-poll chain).
        ``job.dedupe_key`` MUST NOT be ``None``.

        Returns ``(id, inserted)``: ``inserted`` is ``True`` when this call's
        own INSERT won the race, ``False`` when an existing row under the
        same ``dedupe_key`` was found instead. A caller advancing a chain by
        a fresh, never-before-used key should never see ``False`` -- when it
        does, that key was reused, which is exactly the silent-chain-death
        defect this return value exists to make visible (design.md § S5,
        amending S5a2: ``OpenAfterClose.seed`` logs an ERROR on ``False``).
        """
        ...

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
