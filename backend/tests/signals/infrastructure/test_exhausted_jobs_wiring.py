"""Decision 25, task 5c.6: the PRODUCTION worker wires the exhaustion observer.

``ExhaustionObservingJobQueue`` requires its observer, so forgetting it is a
``TypeError``; what this pins is that ``main.build_worker_runner`` actually
claims through it, with the signals recorder on the queue's own session. It
drives the runner ``main.py`` builds, through a real ``signal.process`` job that
cannot succeed (the signal's strategy does not exist, so the handler raises
``UnknownStrategyError``) with ``max_attempts=1``.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.infrastructure.models import SignalRow
from tests.signals.infrastructure.conftest import seed_signal_row

pytestmark = pytest.mark.integration

_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    min_order_size=Decimal("10"),
)


async def test_the_production_worker_rejects_the_signal_of_a_job_that_exhausts_its_retries(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)
    signal_id = uuid4()
    await seed_signal_row(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=uuid4(),  # no such strategy: the handler raises
        idempotency_key="unresolvable",
        symbol="STXUSDT_PERP",
    )
    async with pg_session_factory() as session:
        job_id = await PostgresJobQueue(session).enqueue(
            Job(
                kind=JobKind.SIGNAL_PROCESS,
                payload={"signal_id": str(signal_id)},
                max_attempts=1,
            )
        )
        await session.commit()

    runner = main.build_worker_runner([_POOL], session_factory_override=pg_session_factory)
    assert await runner.run_once() is True

    async with pg_session_factory() as session:
        job = (await session.execute(select(JobRow).where(JobRow.id == job_id))).scalar_one()
        signal = (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()
    assert job.status == "FAILED"
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "JOB_FAILED")
    assert signal.outcome_detail == job.last_error
