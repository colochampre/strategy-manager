"""Owner decision 29: a worker that refuses its own start exits 78.

Systemd runs the worker with ``Restart=always``, so a refusal that exits like
any other failure is restarted every five seconds forever, one Telegram alert
each time. The owner adds ``RestartPreventExitStatus=78`` to the unit; what
this file pins is the process side of that contract:

* every refusal in the startup phase ends the process with 78, after exactly one
  ERROR that reached the alert channel (6e.1, 6e.3);
* nothing that fails AFTER startup exits 78, so it is still restarted, which is
  the documented recovery for a dead recurring chain (6e.2).

Everything runs through ``worker.main``, the real ``operator_alerts`` and the
real ``_run_worker`` sequence. Only the leaves that need PostgreSQL or a venue
are replaced; the checks under test are the production ones. No credential
(rule 1): the alerter records instead of calling Telegram.
"""

import asyncio
import base64
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from strategy_manager import main, worker
from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
)
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    PoolLockKeyCollisionError,
)
from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure import alerting
from strategy_manager.shared.infrastructure.crypto import DecryptionFailed

_VALID_MASTER_KEY = base64.b64encode(bytes(32)).decode()
_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    min_order_size=Decimal("10"),
)
_EX_CONFIG = 78


class RecordingAlerter:
    """Stands in for ``TelegramAlerter``: no token, no network (rule 1)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))

    async def aclose(self) -> None:
        return None


class _AsyncContext:
    def __init__(self, value: object = None) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeEngine:
    def connect(self) -> _AsyncContext:
        return _AsyncContext(object())

    async def dispose(self) -> None:
        return None


class FakePoolRepository:
    pools: Sequence[PoolConfig] = (_POOL,)

    def __init__(self, _conn: object) -> None:
        pass

    async def list_enabled(self) -> Sequence[PoolConfig]:
        return type(self).pools


class FakeVault:
    """One sealed bybit credential, which opens unless told otherwise."""

    opens = True

    def __init__(self, *_: object) -> None:
        pass

    async def hints(self) -> list[CredentialHint]:
        return [CredentialHint(exchange="bybit", label="default", api_key_last4="wxyz")]

    async def load(self, exchange: str) -> ExchangeCredential:
        if not type(self).opens:
            raise DecryptionFailed(f"could not unwrap the data key for '{exchange}'")
        return ExchangeCredential(
            exchange=exchange, label="default", api_key="KEY-wxyz", api_secret="S"
        )


class FakeRunner:
    """``run_forever`` either returns (a clean stop) or raises ``failure``."""

    def __init__(self, failure: BaseException | None = None) -> None:
        self._failure = failure

    async def run_forever(self, stop: asyncio.Event, on_tick: object = None) -> None:
        del stop, on_tick
        if self._failure is not None:
            raise self._failure


async def _no_op(*_: object, **__: object) -> None:
    return None


async def _no_seeds(*_: object, **__: object) -> list[object]:
    return []


@pytest.fixture
def alerter(monkeypatch: pytest.MonkeyPatch) -> RecordingAlerter:
    recording = RecordingAlerter()
    monkeypatch.setattr(alerting, "build_alerter", lambda settings: recording)
    return recording


@pytest.fixture
def startup(monkeypatch: pytest.MonkeyPatch, alerter: RecordingAlerter) -> Settings:
    """A healthy worker: every check passes and the loop stops at once.

    Each test breaks exactly one thing. ``alerts_enabled`` is on so the real
    ``operator_alerts`` installs the real bridge around the real sequence.
    """
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        alerts_enabled=True,
        dry_run=True,
        master_encryption_key=_VALID_MASTER_KEY,
    )
    FakePoolRepository.pools = (_POOL,)
    FakeVault.opens = True
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "_configure_logging", lambda: None)
    monkeypatch.setattr(worker, "engine", FakeEngine())
    monkeypatch.setattr(worker, "session_factory", lambda: _AsyncContext())
    monkeypatch.setattr(worker, "CapitalPoolRepository", FakePoolRepository)
    monkeypatch.setattr(worker, "SqlAlchemyCredentialVault", FakeVault)
    monkeypatch.setattr(worker, "assert_pool_lock_keys_distinct", _no_op)
    monkeypatch.setattr(worker, "assert_dry_run_matches_ledger", _no_op)
    monkeypatch.setattr(worker, "build_worker_runner", lambda *a, **k: FakeRunner())
    monkeypatch.setattr(worker, "_seed_recurring_chains", _no_seeds)
    monkeypatch.setattr(worker, "_install_signal_handlers", lambda: asyncio.Event())
    return settings


def _outcome() -> object:
    """What ``worker.main`` does, as a comparable value: the exit code of a
    ``SystemExit``, the exception class of anything else, ``None`` on a clean
    return. Returned rather than raised so a wrong exit fails on an ASSERTION
    about the outcome, not on an exception escaping the test."""
    try:
        worker.main()
    except SystemExit as exit_:
        return exit_.code
    except Exception as exc:  # noqa: BLE001 - the exception class IS the outcome
        return type(exc).__name__
    return None


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


# --- one break per startup refusal -----------------------------------------


def _break_vault(monkeypatch: pytest.MonkeyPatch, _: Settings) -> None:
    FakeVault.opens = False


def _break_lock_keys(monkeypatch: pytest.MonkeyPatch, _: Settings) -> None:
    async def collide(*_: object, **__: object) -> None:
        raise PoolLockKeyCollisionError(
            "pools (bybit, usdt-m, USDT) and (binance, usdt-m, USDT) both hash "
            "to lock key (1, 2)"
        )

    monkeypatch.setattr(worker, "assert_pool_lock_keys_distinct", collide)


def _break_no_pools(monkeypatch: pytest.MonkeyPatch, _: Settings) -> None:
    FakePoolRepository.pools = ()


def _break_master_key(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(settings, "master_encryption_key", "not base64 at all!")


def _break_mode_guard(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """The REAL use case, over a reader that reports an open rehearsal
    position, so its own ERROR is the one under test."""

    class Reader:
        async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
            return [
                OpenAllocationOrigin(
                    allocation_id=UUID("aaaaaaaa-1111-2222-3333-444444444444"),
                    strategy_name="Alpha",
                    exchange="bybit",
                    venue="usdt-m",
                    settlement_currency="USDT",
                    symbol="SOLUSDT.P",
                    holds_rehearsal_fill=True,
                    holds_live_fill=False,
                )
            ]

        async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
            return []

    async def guard(*, dry_run: bool) -> None:
        await assert_mode_matches_ledger(dry_run=dry_run, reader=Reader())

    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(worker, "assert_dry_run_matches_ledger", guard)


def _break_dry_run_safe(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """The REAL composition root, with DRY_RUN off and a registered adapter
    that is not live -- the configuration ``assert_dry_run_safe`` exists for."""

    class NotLive:
        is_live = False
        exchange = "bybit"
        venues = frozenset({"usdt-m"})

    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "BybitFuturesExchangeAdapter", NotLive)
    monkeypatch.setattr(worker, "build_worker_runner", main.build_worker_runner)


_REFUSALS: list[tuple[str, Callable[[pytest.MonkeyPatch, Settings], None]]] = [
    ("vault self-test", _break_vault),
    ("pool lock-key collision", _break_lock_keys),
    ("no enabled pools", _break_no_pools),
    ("unreadable master key", _break_master_key),
    ("mode guard (decision 28)", _break_mode_guard),
    ("assert_dry_run_safe", _break_dry_run_safe),
]
_IDS = [name for name, _ in _REFUSALS]
_BREAKS = [pytest.param(brk, id=name) for name, brk in _REFUSALS]


def test_a_healthy_start_returns_and_alerts_nobody(
    startup: Settings, alerter: RecordingAlerter, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative control: the harness itself does not refuse."""
    with caplog.at_level(logging.INFO):
        assert _outcome() is None

    assert _errors(caplog) == []
    assert alerter.sent == []


# --- 6e.1 -------------------------------------------------------------------


@pytest.mark.parametrize("brk", _BREAKS)
def test_every_startup_refusal_exits_78(
    brk: Callable[[pytest.MonkeyPatch, Settings], None],
    startup: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brk(monkeypatch, startup)

    assert _outcome() == _EX_CONFIG


# --- 6e.3 -------------------------------------------------------------------


@pytest.mark.parametrize("brk", _BREAKS)
def test_every_startup_refusal_logs_one_error_that_reaches_the_alert_channel(
    brk: Callable[[pytest.MonkeyPatch, Settings], None],
    startup: Settings,
    alerter: RecordingAlerter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    brk(monkeypatch, startup)

    with caplog.at_level(logging.INFO):
        _outcome()

    assert len(_errors(caplog)) == 1
    # ``main`` has returned, so ``operator_alerts`` has already drained: the
    # alert was delivered BEFORE the process could exit.
    assert len(alerter.sent) == 1
    title, body = alerter.sent[0]
    assert "ERROR" in title
    assert body


def test_the_mode_guard_keeps_its_own_error_text(
    startup: Settings,
    alerter: RecordingAlerter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision 28's ERROR names each offender and the way out. Exiting 78 must
    not replace it with a shorter one or add a second beside it."""
    _break_mode_guard(monkeypatch, startup)

    with caplog.at_level(logging.INFO):
        _outcome()

    (error,) = _errors(caplog)
    for expected in ("Alpha", "bybit/usdt-m/USDT", "SOLUSDT.P", "then flip"):
        assert expected in error
    assert expected in alerter.sent[0][1]


def test_a_refusal_never_puts_the_master_key_or_a_traceback_in_the_alert(
    startup: Settings,
    alerter: RecordingAlerter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The refusal is reported by its message, not by ``exc_info``: a traceback
    is where a local variable holding a secret would surface."""
    _break_master_key(monkeypatch, startup)

    with caplog.at_level(logging.INFO):
        _outcome()

    assert all(record.exc_info is None for record in caplog.records)
    assert len(alerter.sent) == 1
    assert "not base64 at all" not in alerter.sent[0][1]
    assert "Traceback" not in alerter.sent[0][1]


# --- 6e.2 -------------------------------------------------------------------


_RUNTIME_FAILURES: list[Callable[[], BaseException]] = [
    lambda: InvariantViolation("a runtime invariant, raised inside a handler"),
    lambda: DecryptionFailed("a credential opened per job stopped decrypting"),
    lambda: PoolLockKeyCollisionError("raised from a reload while running"),
    lambda: RuntimeError("anything else the loop can throw"),
]


@pytest.mark.parametrize("make_failure", _RUNTIME_FAILURES)
def test_a_failure_from_the_running_loop_is_not_a_startup_refusal(
    make_failure: Callable[[], BaseException],
    startup: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same exception classes the startup checks raise, thrown from
    ``run_forever``. They must keep ending the process the way they do today
    (an unhandled exception, non-zero) so systemd restarts it."""
    failure = make_failure()
    monkeypatch.setattr(worker, "build_worker_runner", lambda *a, **k: FakeRunner(failure))

    assert _outcome() == type(failure).__name__


def test_a_failure_while_seeding_the_chains_is_not_a_startup_refusal(
    startup: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeding is the last step of the startup sequence and it talks to the
    database. An outage there is recovered by a restart, so it must not stop
    one -- even when the exception it raises is an ``InvariantViolation``."""

    async def broken(*_: Any, **__: Any) -> list[object]:
        raise InvariantViolation("enqueue_unique requires a dedupe_key")

    monkeypatch.setattr(worker, "_seed_recurring_chains", broken)

    assert _outcome() == "InvariantViolation"


def test_a_failure_from_the_running_loop_logs_no_startup_refusal(
    startup: Settings,
    alerter: RecordingAlerter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        worker, "build_worker_runner", lambda *a, **k: FakeRunner(InvariantViolation("boom"))
    )

    with caplog.at_level(logging.INFO):
        _outcome()

    assert not any("refus" in message.lower() for message in _errors(caplog))
