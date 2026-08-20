"""The worker process entrypoint.

Two processes share one database. The API validates a TradingView alert,
persists it and returns inside the 3-second budget; this process does
everything that takes longer than that — allocation, execution, ledger
writes, reservation expiry and balance syncing.

It composes nothing itself. ``main.build_worker_runner`` stays the single
composition root (design.md § Composition Root), so a handler registered for
the API's view of the world is the same handler the worker runs.

Startup order is deliberate:

1. Load the configured pools and assert their advisory-lock keys are
   distinct. This process is the one that actually takes those locks, so a
   collision here silently serializes two unrelated pools against each other.
2. Assert the ``DRY_RUN`` invariant before any job can be claimed.
3. Seed the recurring chains, so a restart is also the recovery path for a
   chain that died.
4. Only then start claiming.

Run it with::

    cd backend && uv run python -m strategy_manager.worker
"""

import asyncio
import logging
import signal

from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.main import build_worker_runner
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.recurring_jobs import RecurringJobSeeder

logger = logging.getLogger("strategy_manager.worker")


async def run() -> None:
    settings = get_settings()

    async with engine.connect() as conn:
        pools = await CapitalPoolRepository(conn).list_enabled()
        await assert_pool_lock_keys_distinct(conn, pools)

    if not pools:
        raise InvariantViolation(
            "no enabled capital pools are configured; the worker would claim "
            "signals it can never allocate"
        )

    logger.info(
        "worker starting: %d enabled pools, dry_run=%s", len(pools), settings.dry_run
    )

    # Registers the handlers and asserts the DRY_RUN invariant, so an unsafe
    # configuration fails here rather than on the first claimed signal.
    runner = build_worker_runner(pools)

    async with session_factory() as session:
        seeded = await RecurringJobSeeder(session, PostgresJobQueue(session)).seed()
    if seeded:
        logger.info("seeded recurring chains: %s", [kind.value for kind in seeded])
    else:
        logger.info("recurring chains already alive; nothing seeded")

    stop = _install_signal_handlers()
    logger.info("claiming jobs; send SIGINT or SIGTERM to stop")
    await runner.run_forever(stop)

    logger.info("worker stopped")
    await engine.dispose()


def _install_signal_handlers() -> asyncio.Event:
    """``loop.add_signal_handler`` is not implemented on Windows, and this
    runs on Windows, so the portable ``signal.signal`` is used instead. Its
    callback fires outside the event loop's control, hence the hop back onto
    the loop before touching the event.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def request_stop(*_: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, request_stop)

    return stop


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - a race with the handler above
        logger.info("interrupted")


if __name__ == "__main__":
    main()
