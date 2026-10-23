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
1b. Refuse to start when ``DRY_RUN`` does not match the origin of an open
   position or an unsettled order in the ledger (decision 28). Deliberately a
   refusal and not a degraded start: the flip is a manual act done with a
   restart, and a degraded worker would have to guard every signal instead.
2. Open every sealed credential once, so a master key that does not match the
   vault is a refusal to start rather than a per-job failure.
3. Log, but never refuse, a CONFIGURED exchange with no active key at all
   (``_assert_keys_present``) — DEGRADED (decision 20), not a startup
   refusal. The composition root re-checks this per job, so a key saved or
   deleted while the worker runs is seen on the next job, not only after a
   restart; this step only seeds that per-job tracker so the first check
   never re-logs what startup already reported. It has to run before the
   composition root is built, which is why the next step comes after it.
3b. Build the composition root, which asserts the ``DRY_RUN`` invariant —
   still before any job can be claimed.
4. Seed the recurring chains, so a restart is also the recovery path for a
   chain that died.
5. Only then start claiming — re-seeding on a cadence from inside that loop,
   because a restart being the ONLY recovery path meant a dead chain waited
   for a human. One did, for 19 hours.

Exit codes (owner decision 29). A refusal in steps 1 to 3b raises
``StartupRefused`` after exactly one ERROR, and ``main`` exits 78 (``EX_CONFIG``)
so a unit with ``RestartPreventExitStatus=78`` stays stopped instead of looping
on it. Anything else -- a database outage during startup, seeding, or any
failure of the running loop -- keeps escaping as an unhandled exception, exits
non-zero and is restarted, which is the recovery for a dead recurring chain.

Run it with::

    cd backend && uv run python -m strategy_manager.worker
"""

import asyncio
import functools
import logging
import signal
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from uuid import UUID

from strategy_manager.accounts.application.ports import CredentialVaultPort
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.key_coverage import (
    UserExchange,
    read_key_coverage,
)
from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    PoolLockKeyCollisionError,
    assert_pool_lock_keys_distinct,
)
from strategy_manager.main import assert_dry_run_matches_ledger, build_worker_runner
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.watchdog import AlertChannelPort
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from strategy_manager.shared.infrastructure.alerting import operator_alerts
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import DecryptionFailed, EnvelopeCipher
from strategy_manager.shared.infrastructure.http_logging import silence_http_client_info_logs
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.recurring_jobs import (
    RecurringChainRevival,
    RecurringJobSeeder,
)

logger = logging.getLogger("strategy_manager.worker")

# sysexits.h ``EX_CONFIG``: the process was configured in a way it cannot run.
# ``os.EX_CONFIG`` does not exist on Windows, where this is developed.
EX_CONFIG = 78


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


@contextmanager
def _startup_refusal() -> Iterator[None]:
    """Turns a startup CHECK's failure into ``StartupRefused``, logging its
    ERROR first when the check did not (owner decision 29).

    Wrapped around each refusal-capable call in ``_run_worker`` and nowhere
    else, and lexically over before ``run_forever``, so a failure of the running
    loop cannot pass through it. It converts instead of having each check raise
    ``StartupRefused`` itself because the checks are shared with code that runs
    after startup: ``EnvelopeCipher.from_base64`` runs per job, the lock-key
    check re-runs every ``balance.sync`` cycle, and both signal failure with
    the generic exceptions caught here. Raising the startup type from inside
    them would make the running worker exit 78 too.

    The ERROR is logged here, in the process that is about to exit, because the
    alert bridge forwards log records and never exceptions. It carries the
    message only, no ``exc_info``: a traceback is where a local variable
    holding a secret would surface. The original exception stays as
    ``__cause__``.
    """
    try:
        yield
    except StartupRefused as refused:
        if not refused.logged:
            logger.error("refusing to start: %s", refused)
        raise
    except (InvariantViolation, PoolLockKeyCollisionError) as exc:
        logger.error("refusing to start: %s", exc)
        raise StartupRefused(str(exc), logged=True) from exc


async def _run_worker(settings: Settings, alert_channel: AlertChannelPort | None) -> None:
    async with engine.connect() as conn:
        pools = await CapitalPoolRepository(conn).list_enabled()
        with _startup_refusal():
            await assert_pool_lock_keys_distinct(conn, pools)

    if not pools:
        with _startup_refusal():
            raise StartupRefused(
                "no enabled capital pools are configured; the worker would claim "
                "signals it can never allocate"
            )

    logger.info(
        "worker starting: %d enabled pools, dry_run=%s", len(pools), settings.dry_run
    )

    # Decision 28. DRY_RUN is configuration, and flipping it with a position
    # still open sends that position's close to the other exchange: a live
    # position closed against the fake one is booked flat while it stays open
    # at the venue. So a mismatch REFUSES to start (unlike decision 20's
    # degraded start), through the same exception every other startup
    # invariant here uses. It runs inside ``operator_alerts`` -- see ``run`` --
    # so the ERROR it logs first reaches Telegram before the process exits.
    #
    # That guard raises ``StartupRefused`` itself (it is startup-only and has
    # already logged its ERROR); the wrapper only keeps it from being logged
    # twice.
    with _startup_refusal():
        await assert_dry_run_matches_ledger(dry_run=settings.dry_run)

    # A master key that is well-formed but WRONG only fails when a credential
    # is actually opened — per job, inside a handler, as DecryptionFailed.
    # That is five retries and a FAILED job per signal, and for balance.sync
    # it kills the recurring chain with nothing scheduled to revive it.
    # Opening every sealed credential once, here, BEFORE the composition root
    # is even built, turns a mismatched key into a refusal to start.
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
        with _startup_refusal():
            cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
        # The users holding an active key, and the pairs that hold one, from
        # one statement with no decrypt (multi-user design AD9). Kept apart
        # from ``opened``: that list is the DECRYPT self-test's own evidence,
        # and re-purposing it here would tie a MISSING-key report to a decrypt
        # attempt that never happened for the pair in question.
        active = (await read_key_coverage(session)).active
        users = sorted({user_id for user_id, _ in active}, key=str)
        with _startup_refusal():
            opened = await _assert_sealed_credentials_open(vault, users)
    _log_vault_self_test(opened, dry_run=settings.dry_run)

    # Which CONFIGURED pairs have no active key AT ALL — DEGRADED
    # (decision 20), never a startup refusal (see ``_assert_keys_present``'s
    # own docstring for the full reasoning and its per-job continuation).
    degraded = _assert_keys_present(active, pools)

    # Registers the handlers and asserts the DRY_RUN invariant, so an unsafe
    # configuration fails here rather than on the first claimed signal.
    # ``initial_degraded`` seeds the composition root's own per-job tracker,
    # so the very first job-level check never re-logs what this function
    # already reported above.
    with _startup_refusal():
        runner = build_worker_runner(
            pools, alert_channel=alert_channel, initial_degraded=degraded
        )

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


def _log_vault_self_test(opened: Sequence[UserExchange], *, dry_run: bool) -> None:
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
            ", ".join(f"{exchange} of user {str(user_id)[:8]}" for user_id, exchange in opened),
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


async def _assert_sealed_credentials_open(
    vault: CredentialVaultPort, users: Sequence[UUID]
) -> list[UserExchange]:
    """Opens every active credential of every user in ``users`` once, each as
    its own user (multi-user design AD9), and names the pairs it opened.

    One key that does not open still refuses the whole start, whoever it
    belongs to (tasks.md B.7: unchanged): the master key is the process's, not
    a user's, so a row it cannot open says the same about every row. The
    refusal names the user by the first 8 hex of their id, never an e-mail.

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
    opened: list[UserExchange] = []
    for user_id in users:
        for hint in await vault.hints(user_id):
            try:
                await vault.load(user_id, hint.exchange)
            except DecryptionFailed as exc:
                raise InvariantViolation(
                    f"the sealed credential for '{hint.exchange}' (key ***"
                    f"{hint.api_key_last4}) of user {str(user_id)[:8]} cannot be "
                    "decrypted. Refusing to start: MASTER_ENCRYPTION_KEY does not "
                    "match the key these rows were sealed with, or the rows were "
                    "altered. Supply the original key — a different one cannot be "
                    "made to read them, and re-sealing means storing every "
                    "exchange credential again."
                ) from exc
            opened.append((user_id, hint.exchange))
    return opened


def _assert_keys_present(
    active: frozenset[UserExchange], pools: Sequence[PoolConfig]
) -> frozenset[UserExchange]:
    """Which CONFIGURED ``(user, exchange)`` pairs (that user holds an enabled
    pool there) have NO active vault credential of that user's, right now.
    Another user's key never covers a pair (multi-user design AD9), and the
    ERROR names the user by the first 8 hex of their id, never an e-mail.

    Never raises: a missing key is DEGRADED (decision 20), not a startup
    refusal. The worker still starts, still trades every OTHER exchange, and
    this only logs one ERROR per missing exchange -- reaching Telegram
    through the alert bridge -- so an operator learns about it immediately
    rather than discovering it the first time a signal on that exchange
    silently reserves capital it can never place (``_vault_credential``'s own
    docstring, main.py, names that exact cost for the trade-client side of
    this same degradation).

    A per-exchange check, not a single boolean: an unrelated exchange's
    missing key must never be reported against the wrong name, or fixing
    "binance" would send an operator chasing the wrong row.

    This is the STARTUP report only. The composition root re-checks the same
    active-key listing on its own per-job cadence (``read_key_coverage``
    / ``main._track_degraded_exchanges``), seeded with this function's return
    value so a key saved or deleted while the worker is already running is
    seen on the next job -- not only after a restart -- and the very first
    per-job check never repeats what this function already logged.
    """
    configured = {(pool.user_id, pool.exchange.value) for pool in pools}
    degraded = frozenset(configured - active)
    for user_id, exchange in sorted(degraded, key=lambda pair: (pair[1], str(pair[0]))):
        logger.error(
            "'%s' has an enabled pool but no active vault credential for user %s; "
            "that user's reads and orders there are skipped until one is stored "
            "(uv run python scripts/store_%s_credentials.py --user-email <theirs>)",
            exchange,
            str(user_id)[:8],
            exchange,
        )
    return degraded


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
    silence_http_client_info_logs()


def main() -> None:
    _configure_logging()
    try:
        asyncio.run(run())
    except StartupRefused:
        # Already logged at ERROR inside ``operator_alerts``, which drained the
        # alert bridge on the way out, so nothing is printed here: an unhandled
        # exception would add a traceback to a refusal whose message is the
        # whole story. 78 (EX_CONFIG) is what the unit's
        # ``RestartPreventExitStatus=78`` recognises (owner decision 29). It is
        # the ONLY exception mapped: everything else still escapes as an
        # unhandled exception, exits non-zero and is restarted.
        sys.exit(EX_CONFIG)
    except KeyboardInterrupt:  # pragma: no cover - a race with the handler above
        logger.info("interrupted")


if __name__ == "__main__":
    main()
