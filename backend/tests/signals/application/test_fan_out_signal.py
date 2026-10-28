"""``FanOutSignal``'s one transaction, against fakes that record the calls
(tasks.md C.5). The rules of who is eligible are proven on PostgreSQL in
``tests/signals/infrastructure/test_fan_out_integration.py``."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.application.ports import StrategyPolicySnapshot
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.signals.application.fan_out_signal import (
    FanOutSignal,
    SignalFacts,
    Subscriber,
)
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.outcome import SignalOutcome

_STRATEGY = uuid4()


class _Log:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _Facts:
    async def load(self, signal_id: UUID) -> SignalFacts:
        return SignalFacts(_STRATEGY, "STXUSDT.P", Decimal("1"), None, datetime.now(UTC))


class _Policy:
    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        return StrategyPolicySnapshot(
            strategy_id=strategy_id,
            enabled=True,
            fill_mode="PARTIAL",
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            allocation_percent=Decimal("30"),
            author_id=uuid4(),
        )


class _Subscribers:
    def __init__(self, active: list[Subscriber]) -> None:
        self._active = active

    async def active(self, strategy_id: UUID, received_at: datetime) -> list[Subscriber]:
        return self._active

    async def live_holders(
        self, strategy_id: UUID, symbol: str, pool: PoolKey, received_at: datetime
    ) -> list[Subscriber]:
        return []


class _Deliveries:
    def __init__(self, log: _Log) -> None:
        self._log = log

    async def ensure(
        self, signal_id: UUID, subscriptions: Sequence[Subscriber]
    ) -> dict[UUID, UUID]:
        self._log.calls.append("deliveries")
        return {subscriber.subscription_id: uuid4() for subscriber in subscriptions}


class _Jobs:
    def __init__(self, log: _Log) -> None:
        self._log = log
        self.jobs: list[Job] = []

    async def enqueue_unique(self, job: Job) -> tuple[UUID, bool]:
        self._log.calls.append("job")
        self.jobs.append(job)
        return uuid4(), True


class _Outcomes:
    def __init__(self, log: _Log) -> None:
        self._log = log

    async def record(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        self._log.calls.append("outcome")


class _Commit:
    def __init__(self, log: _Log) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.calls.append("commit")


async def test_deliveries_and_jobs_are_written_and_committed_once_at_the_end() -> None:
    log = _Log()
    jobs = _Jobs(log)
    subscribers = [Subscriber(uuid4(), uuid4(), True), Subscriber(uuid4(), uuid4(), True)]
    use_case = FanOutSignal(
        facts=_Facts(),
        strategy_policy=_Policy(),
        subscribers=_Subscribers(subscribers),
        deliveries=_Deliveries(log),
        jobs=jobs,  # type: ignore[arg-type]
        outcomes=_Outcomes(log),  # type: ignore[arg-type]
        commit=_Commit(log),
    )

    result = await use_case.run(uuid4())

    assert log.calls == ["deliveries", "job", "job", "commit"]
    assert [job.kind for job in jobs.jobs] == [JobKind.DELIVERY_PROCESS] * 2
    assert [job.dedupe_key for job in jobs.jobs] == [
        f"delivery:{delivery_id}" for delivery_id in result.delivery_ids
    ]
    assert [job.payload["delivery_id"] for job in jobs.jobs] == [
        str(delivery_id) for delivery_id in result.delivery_ids
    ]
