"""IngestSignal: the sole entry point that turns an authenticated alert into
a persisted signal and an enqueued job — never executes a trade inline
(spec: signal-ingress § Idempotent Signal Persistence, § Fast Enqueue-Only
Response).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import JobQueuePort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.signals.application.ports import CommitPort, SignalRepositoryPort
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal


class MissingIdempotencyKeyError(DomainError):
    """Raised when the derived idempotency key is blank."""


@dataclass(frozen=True, slots=True)
class IngestCommand:
    """Everything IngestSignal needs, already parsed from the alert."""

    strategy_id: UUID
    idempotency_key: str
    action: str
    contracts: Decimal
    position_size: Decimal
    price: Decimal
    symbol: str
    signal_type: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngestResult:
    signal_id: UUID
    duplicate: bool


class IngestSignal:
    """Persists a signal idempotently and enqueues its processing job."""

    def __init__(
        self,
        repository: SignalRepositoryPort,
        job_queue: JobQueuePort,
        uow: CommitPort,
    ) -> None:
        self._repository = repository
        self._job_queue = job_queue
        self._uow = uow

    async def ingest(self, command: IngestCommand) -> IngestResult:
        if not command.idempotency_key.strip():
            raise MissingIdempotencyKeyError(
                "the alert payload is missing a usable idempotency key"
            )

        signal = WebhookSignal(
            strategy_id=command.strategy_id,
            idempotency_key=IdempotencyKey(command.idempotency_key),
            action=command.action,
            contracts=command.contracts,
            position_size=command.position_size,
            price=command.price,
            symbol=command.symbol,
            signal_type=command.signal_type,
            raw_payload=command.raw_payload,
            status=SignalStatus.ACCEPTED,
        )

        outcome = await self._repository.insert_or_get(signal)
        if outcome.inserted:
            await self._job_queue.enqueue(
                Job(
                    kind=JobKind.SIGNAL_PROCESS,
                    payload={"signal_id": str(outcome.signal_id)},
                )
            )

        await self._uow.commit()
        return IngestResult(signal_id=outcome.signal_id, duplicate=not outcome.inserted)
