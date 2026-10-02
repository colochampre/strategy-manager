"""Unit tests for IngestSignal, using fake ports (no DB).

Covers spec: signal-ingress § Idempotent Signal Persistence.
"""

import inspect
import logging
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
from strategy_manager.signals.application.ports import InsertOutcome, UnknownSignalStrategy
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


async def test_archived_strategy_webhook_persists_signal_unchanged_no_lookup_added() -> None:
    """decision 11: a signal for an ARCHIVED strategy is persisted by the
    webhook exactly like any other -- the refusal happens later, during
    processing (``process_signal.py``'s ``_refuse_archived_strategy``,
    unit 2b), never at ingress. ``IngestSignal`` does not know, and must
    never be made to know, whether ``command.strategy_id`` is archived: a
    lookup here would still leave the idempotency window open on the read
    (the strategy could archive between the read and the insert), and would
    duplicate the one authoritative archived check design.md § 8 already
    places on the processing path.

    This is a REGRESSION guard, not new behaviour -- ``IngestSignal``
    already performs no strategy lookup of any kind, so a positive
    behavioural assertion alone cannot catch a lookup being ADDED later; the
    constructor-signature assertion below is what actually would. Proven
    non-vacuous by temporarily adding a ``strategy_policy`` parameter to
    ``IngestSignal.__init__`` and watching this test fail on that assertion,
    then reverting -- see this unit's apply-progress for the RED line."""
    repository = FakeSignalRepository()
    job_queue = FakeJobQueue()
    uow = FakeUnitOfWork()
    use_case = IngestSignal(repository=repository, job_queue=job_queue, uow=uow)

    result = await use_case.ingest(_command(strategy_id=uuid4()))

    assert result.duplicate is False
    assert len(repository.inserted_signals) == 1
    assert len(job_queue.enqueued) == 1
    assert uow.committed is True

    # Structural half of the guard: ``IngestSignal`` must accept no
    # strategy-lookup port at all, so there is nothing to call even by
    # accident.
    constructor_params = set(inspect.signature(IngestSignal.__init__).parameters)
    assert not constructor_params & {
        "strategy_policy",
        "strategy_repository",
        "strategy_lookup",
    }


# --- an alert whose strategy is not registered (unit 9xa) -------------------


class UnregisteredStrategyRepository:
    """The database refused the insert on the foreign key into ``strategies``."""

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome:
        raise UnknownSignalStrategy(signal.strategy_id)


def _unregistered_use_case() -> tuple[IngestSignal, FakeJobQueue, FakeUnitOfWork]:
    job_queue = FakeJobQueue()
    uow = FakeUnitOfWork()
    use_case = IngestSignal(
        repository=UnregisteredStrategyRepository(), job_queue=job_queue, uow=uow
    )
    return use_case, job_queue, uow


async def test_an_unregistered_strategy_logs_one_warning_naming_the_id_and_the_alerts_symbol_and_reraises(  # noqa: E501
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case, _, _ = _unregistered_use_case()
    strategy_id = uuid4()
    command = _command(strategy_id=strategy_id, symbol="STXUSDT.P")

    with caplog.at_level(logging.DEBUG), pytest.raises(UnknownSignalStrategy) as raised:
        await use_case.ingest(command)

    assert raised.value.strategy_id == strategy_id
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert str(strategy_id) in message
    assert "STXUSDT.P" in message
    assert warnings[0].exc_info is None


async def test_nothing_is_enqueued_and_nothing_is_committed_for_an_unregistered_strategy() -> None:
    use_case, job_queue, uow = _unregistered_use_case()

    with pytest.raises(UnknownSignalStrategy):
        await use_case.ingest(_command())

    assert job_queue.enqueued == []
    assert uow.committed is False


async def test_the_warning_carries_no_raw_payload(caplog: pytest.LogCaptureFixture) -> None:
    use_case, _, _ = _unregistered_use_case()
    canary = "RAW-PAYLOAD-CANARY-7f3a"
    command = _command(raw_payload={"signal_param": canary, "secret": canary})

    with caplog.at_level(logging.DEBUG), pytest.raises(UnknownSignalStrategy):
        await use_case.ingest(command)

    assert caplog.records
    assert all(canary not in record.getMessage() for record in caplog.records)
    assert all(canary not in str(record.args) for record in caplog.records)
