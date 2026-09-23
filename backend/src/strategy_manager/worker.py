"""The worker process entrypoint.

Two processes share one database. The API validates a TradingView alert,
persists it and returns inside the 3-second budget; this process does
everything that takes longer than that — allocation, execution, ledger
writes, reservation expiry and balance syncing.

It composes nothing itself. ``main.build_worker_runner`` stays the single
composition root (design.md § Composition Root), so a handler registered for
the API's view of the world is the same handler the worker runs.

Startup order is deliberate:

0. Install operator alerting, before anything that can refuse to start. Every
   step below ends the process on failure, and a worker that dies during
   startup is precisely the worker nobody notices has died.
1. Load the configured pools and assert their advisory-lock keys are
   distinct. This process is the one that actually takes those locks, so a
   collision here silently serializes two unrelated pools against each other.
2. Assert the ``DRY_RUN`` invariant before any job can be claimed.
3. Open every sealed credential once, so a master key that does not match the
   vault is a refusal to start rather than a per-job failure.
4. Seed the recurring chains, so a restart is also the recovery path for a
   chain that died.
5. Only then start claiming — re-seeding on a cadence from inside that loop,
   because a restart being the ONLY recovery path meant a dead chain waited
   for a human. One did, for 19 hours.

Run it with::

    cd backend && uv run python -m strategy_manager.worker
"""

import asyncio
import functools
import logging
import signal

from strategy_manager.accounts.application.ports import CredentialVaultPort
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.main import build_worker_runner
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.watchdog import AlertChannelPort
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.alerting import operator_alerts
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import DecryptionFailed, EnvelopeCipher
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.recurring_jobs import (
    RecurringChainRevival,
    RecurringJobSeeder,
)

logger = logging.getLogger("strategy_manager.worker")


async def run() -> None:
    settings = get_settings()

    # Installed FIRST, before any other startup step, and deliberately so.
    # Every refusal below this line is an ERROR or an ``InvariantViolation``
    # that ends the process, and a worker that dies during startup is exactly
    # the worker nobody notices has died. It needs no credential beyond the
    # settings token — no vault, no database, no venue — so there is nothing
    # it has to wait for. When alerting is off this is a no-op.
    #
    # The bridge itself is carried into the composition root because the
    # watchdog asks it one question — how many alerts it has thrown away. A
    # channel that is dropping alerts is a channel whose silence proves
    # nothing, and it is the one failure the alert path cannot report about
    # itself: whatever the dropped alert was carrying never arrived.
    async with operator_alerts(settings) as bridge:
        await _run_worker(settings, bridge)


async def _run_worker(settings: Settings, alert_channel: AlertChannelPort | None) -> None:
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
    # configuration fails here rather than on the first claimed signal. It also
    # builds the cipher, so a missing or malformed MASTER_ENCRYPTION_KEY has
    # already failed before the block below runs.
    runner = build_worker_runner(pools, alert_channel=alert_channel)

    # A master key that is well-formed but WRONG survives all of that: it
    # builds a cipher fine and only fails when a credential is actually opened
    # — per job, inside a handler, as DecryptionFailed. That is five retries
    # and a FAILED job per signal, and for balance.sync it kills the recurring
    # chain with nothing scheduled to revive it. Opening every sealed
    # credential once, here, turns a mismatched key into a refusal to start.
    #
    # Not a degradation: crypto.py states that a wrong master key, a tampered
    # row and a value moved between rows are the same instruction — stop.
    # It runs under DRY_RUN TOO, and that is a deliberate change (2026-09-22).
    # It used to be skipped there, on the reasoning that a rehearsal must never
    # depend on a sealed key. But DRY_RUN fakes ORDERS, not balances:
    # ``balance.sync`` opens the stored credential on its own cadence either
    # way, confirmed live on the deploy of that date. So under DRY_RUN a
    # mismatched key did not go unused — it failed inside that handler, over
    # and over, while startup reported the vault as unread. An EMPTY vault is
    # still not a failure, so a first boot with nothing sealed is unaffected.
    async with session_factory() as session:
        # The cipher is rebuilt rather than reached for inside the runner:
        # it is one key derivation, and the alternative is widening the
        # composition root's return type so a startup check can borrow a
        # handle to a secret.
        opened = await _assert_sealed_credentials_open(
            SqlAlchemyCredentialVault(
                session,
                EnvelopeCipher.from_base64(settings.master_encryption_key),
                SystemClock(),
            )
        )
    _log_vault_self_test(opened, dry_run=settings.dry_run)

    clock = SystemClock()

    # The startup seed. INFO, because seeding at startup is NORMAL: a chain has
    # to begin somewhere and on a fresh deployment every one of them does. The
    # identical call inside the loop below means something else entirely — see
    # ``RecurringChainRevival``.
    seeded = await _seed_recurring_chains(settings)
    if seeded:
        logger.info("seeded recurring chains: %s", [kind.value for kind in seeded])
    else:
        logger.info("recurring chains already alive; nothing seeded")

    # Same seeder, same query, opposite meaning. A chain seeded from here was
    # alive when this process started and has since exhausted its retries, so
    # the revival is logged at WARNING and names what died.
    revival = RecurringChainRevival(
        seed=functools.partial(_seed_recurring_chains, settings),
        clock=clock,
        interval_seconds=settings.recurring_seed_interval_seconds,
        last_seeded_at=clock.now(),
    )

    stop = _install_signal_handlers()
    logger.info("claiming jobs; send SIGINT or SIGTERM to stop")
    await runner.run_forever(stop, on_tick=revival.revive_if_due)

    logger.info("worker stopped")
    await engine.dispose()


async def _seed_recurring_chains(settings: Settings) -> list[JobKind]:
    """One seeding pass on its own fresh session.

    A session per pass rather than one held open for the life of the process:
    the seeder takes ``pg_advisory_xact_lock``, which is released when its
    transaction ends, and a connection kept open across hours of idle polling is
    a connection that can silently go stale.
    """
    async with session_factory() as session:
        return await RecurringJobSeeder(
            session,
            PostgresJobQueue(
                session,
                backoff_base_seconds=settings.job_retry_backoff_base_seconds,
                backoff_max_seconds=settings.job_retry_backoff_max_seconds,
            ),
        ).seed()


def _log_vault_self_test(opened: list[str], *, dry_run: bool) -> None:
    """An EMPTY vault is not a failure. A fresh deployment has sealed nothing
    yet, and the sealing scripts need this database and this configuration to
    run at all — refusing here would make the first boot impossible.

    The empty case names the job that will actually suffer. Under DRY_RUN that
    is ``balance.sync``, which reads real balances and so needs a real
    credential; without one the deployment stops learning its own capital while
    looking alive. Live, the first cost arrives earlier still: capital is
    reserved and the order cannot be placed.
    """
    if opened:
        logger.info(
            "vault self-test: %d sealed credential(s) opened (%s)",
            len(opened),
            ", ".join(opened),
        )
    elif dry_run:
        logger.warning(
            "vault self-test: no credentials are sealed yet, so nothing was "
            "checked. DRY_RUN fakes orders, not balances: balance.sync will "
            "keep failing until one is stored."
        )
    else:
        logger.warning(
            "vault self-test: no credentials are sealed yet, so nothing was "
            "checked. Live trading will reserve capital and then fail to place "
            "orders until one is stored."
        )


async def _assert_sealed_credentials_open(vault: CredentialVaultPort) -> list[str]:
    """Opens every active credential once and names the exchanges it opened.

    ``hints`` is already the enumeration of active credentials and is the only
    listing that may be rendered, so the failure can name the exchange and the
    last four characters of its key without ever holding a plaintext that
    outlives this function: each ``load`` result is dropped where it is
    produced, never bound, never logged (CLAUDE.md rule 8).

    The message deliberately does not suggest a workaround. There isn't one: a
    key that cannot open these rows is either the wrong key — in which case the
    right one is what must be supplied — or the rows were altered, in which case
    nothing here should be used.
    """
    opened: list[str] = []
    for hint in await vault.hints():
        try:
            await vault.load(hint.exchange)
        except DecryptionFailed as exc:
            raise InvariantViolation(
                f"the sealed credential for '{hint.exchange}' (key ***"
                f"{hint.api_key_last4}) cannot be decrypted. Refusing to start: "
                "MASTER_ENCRYPTION_KEY does not match the key these rows were "
                "sealed with, or the rows were altered. Supply the original key "
                "— a different one cannot be made to read them, and re-sealing "
                "means storing every exchange credential again."
            ) from exc
        opened.append(hint.exchange)
    return opened


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


def _configure_logging() -> None:
    """INFO for this system, WARNING for the HTTP client underneath it.

    ``httpx`` logs one INFO line per request. This process reads a balance per
    exchange every 60s and polls continuations every few seconds, which came to
    roughly 10,800 lines a day on the production host -- and the log an
    operator reads during an incident is the one thing that must not be
    drowned. Those lines also render the signed venue URL, ``timestamp`` and
    ``signature`` included; the signature is timestamp-bound and the API key
    travels in a header, so it is noise rather than a leak, but it is noise
    with no reason to exist.

    WARNING rather than silence, deliberately: a request that FAILS still has
    to say so, and that is the line nobody wants suppressed.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    for chatty in ("httpx", "httpcore"):
        logging.getLogger(chatty).setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - a race with the handler above
        logger.info("interrupted")


if __name__ == "__main__":
    main()
