"""Unit tests for IngestSignal, using fake ports (no DB).

Covers spec: signal-ingress § Idempotent Signal Persistence.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.signals.application.ingest_signal import (
    IngestCommand,
    IngestSignal,
    MissingIdempotencyKeyError,
)
from strategy_manager.signals.application.ports import InsertOutcome
from strategy_manager.signals.domain.signal import WebhookSignal


class FakeSignalRepository:
    """Simulates ``ON CONFLICT (strategy_id, idempotency_key) DO NOTHING``."""

    def __init__(self) -> None:
        self.signals: dict[tuple[UUID, str], UUID] = {}
        self.inserted_signals: list[WebhookSignal] = []

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome:
        key = (signal.strategy_id, signal.idempotency_key.value)
        existing_id = self.signals.get(key)
        if existing_id is not None:
            return InsertOutcome(signal_id=existing_id, inserted=False)

        new_id = uuid4()
        self.signals[key] = new_id
        self.inserted_signals.append(signal)
        return InsertOutcome(signal_id=new_id, inserted=True)


@dataclass
class FakeJobQueue:
    enqueued: list[Job] = field(default_factory=list)

    async def enqueue(self, job: Job) -> UUID:
        self.enqueued.append(job)
        return uuid4()

    async def enqueue_unique(self, job: Job) -> tuple[UUID, bool]:
        raise NotImplementedError

    async def claim(self) -> Any:
        raise NotImplementedError

    async def ack(self, job_id: UUID) -> None:
        raise NotImplementedError

    async def fail(self, job_id: UUID, error: str) -> None:
        raise NotImplementedError


@dataclass
class FakeUnitOfWork:
    committed: bool = False

    async def commit(self) -> None:
        self.committed = True


def _command(**overrides: Any) -> IngestCommand:
    defaults: dict[str, Any] = dict(
        strategy_id=uuid4(),
        idempotency_key="a" * 64,
        action="buy",
        contracts=Decimal("10"),
        position_size=Decimal("10"),
        price=Decimal("50000.5"),
        symbol="BTCUSDT",
        signal_type="a6a28229-9286-463f-99e8-5f48eb597d19",
        raw_payload={"symbol": "BTCUSDT"},
    )
    defaults.update(overrides)
    return IngestCommand(**defaults)


async def test_missing_idempotency_key_is_rejected_without_persisting_or_enqueueing() -> None:
    repository = FakeSignalRepository()
    job_queue = FakeJobQueue()
    uow = FakeUnitOfWork()
    use_case = IngestSignal(repository=repository, job_queue=job_queue, uow=uow)

    with pytest.raises(MissingIdempotencyKeyError):
        await use_case.ingest(_command(idempotency_key=""))

    assert repository.inserted_signals == []
    assert job_queue.enqueued == []
    assert uow.committed is False


async def test_first_delivery_persists_exactly_one_signal_and_enqueues_exactly_one_job() -> None:
    repository = FakeSignalRepository()
    job_queue = FakeJobQueue()
    uow = FakeUnitOfWork()
    use_case = IngestSignal(repository=repository, job_queue=job_queue, uow=uow)

    result = await use_case.ingest(_command())

    assert result.duplicate is False
    assert len(repository.inserted_signals) == 1
    assert len(job_queue.enqueued) == 1
    assert job_queue.enqueued[0].kind == JobKind.SIGNAL_PROCESS
    assert job_queue.enqueued[0].payload == {"signal_id": str(result.signal_id)}
    assert uow.committed is True


async def test_duplicate_delivery_resumes_without_a_second_row_or_job() -> None:
    repository = FakeSignalRepository()
    job_queue = FakeJobQueue()
    uow = FakeUnitOfWork()
    use_case = IngestSignal(repository=repository, job_queue=job_queue, uow=uow)
    command = _command()

    first = await use_case.ingest(command)
    second = await use_case.ingest(command)

    assert second.signal_id == first.signal_id
    assert second.duplicate is True
    assert len(repository.inserted_signals) == 1
    assert len(job_queue.enqueued) == 1
