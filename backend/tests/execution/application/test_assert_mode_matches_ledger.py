"""Decision 28: the startup use case. It logs ONE ERROR naming every offender
and then refuses to start; when nothing offends it says nothing at all.

The reader is a fake here, the SQL is proven on real PostgreSQL elsewhere.
What this file adds is the property that makes the guard worth having: the
ERROR reaches the operator's Telegram before the process exits.
"""

import logging
from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from strategy_manager.shared.infrastructure import alerting
from strategy_manager.shared.infrastructure.alerting import operator_alerts

ALLOCATION = UUID("aaaaaaaa-1111-2222-3333-444444444444")
ATTEMPT = UUID("bbbbbbbb-1111-2222-3333-444444444444")


class FakeReader:
    def __init__(
        self,
        opened: Sequence[OpenAllocationOrigin] = (),
        in_flight: Sequence[InFlightAttemptOrigin] = (),
    ) -> None:
        self._opened = opened
        self._in_flight = in_flight

    async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
        return self._opened

    async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
        return self._in_flight


def _open(*, rehearsal: bool, live: bool, name: str = "Alpha") -> OpenAllocationOrigin:
    return OpenAllocationOrigin(
        allocation_id=ALLOCATION if name == "Alpha" else uuid4(),
        strategy_name=name,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="SOLUSDT.P",
        holds_rehearsal_fill=rehearsal,
        holds_live_fill=live,
    )


def _order(order_id: str) -> InFlightAttemptOrigin:
    return InFlightAttemptOrigin(
        attempt_id=ATTEMPT,
        strategy_name="Beta",
        exchange="binance",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        exchange_order_id=order_id,
    )


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# --- 6d.1 -----------------------------------------------------------------


async def test_live_start_over_an_open_rehearsal_position_logs_one_error_and_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(opened=[_open(rehearsal=True, live=False)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(dry_run=False, reader=reader)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    for expected in ("Alpha", "bybit/usdt-m/USDT", "SOLUSDT.P", str(ALLOCATION)):
        assert expected in message
    assert "DRY_RUN=true" in message
    assert "then flip DRY_RUN" in message


# --- 6d.2 -----------------------------------------------------------------


async def test_dry_run_start_over_an_open_live_position_logs_one_error_and_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(opened=[_open(rehearsal=False, live=True)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(dry_run=True, reader=reader)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "Alpha" in message
    assert "DRY_RUN=false" in message
    assert "still be open on the venue" in message


# --- 6d.3 -----------------------------------------------------------------


async def test_nothing_open_starts_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(dry_run=False, reader=FakeReader())
        await assert_mode_matches_ledger(dry_run=True, reader=FakeReader())

    assert caplog.records == []


async def test_only_positions_of_the_current_mode_start_and_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(
            dry_run=False, reader=FakeReader(opened=[_open(rehearsal=False, live=True)])
        )
        await assert_mode_matches_ledger(
            dry_run=True, reader=FakeReader(opened=[_open(rehearsal=True, live=False)])
        )

    assert caplog.records == []


# --- both kinds, every offender, in-flight orders ---------------------------


async def test_an_allocation_holding_both_kinds_refuses_in_either_mode() -> None:
    reader = FakeReader(opened=[_open(rehearsal=True, live=True)])

    for dry_run in (True, False):
        with pytest.raises(StartupRefused):
            await assert_mode_matches_ledger(dry_run=dry_run, reader=reader)


async def test_one_error_names_every_offender_not_one_error_each(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(
        opened=[
            _open(rehearsal=True, live=False, name="Alpha"),
            _open(rehearsal=True, live=False, name="Gamma"),
        ],
        in_flight=[_order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}")],
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(dry_run=False, reader=reader)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    for expected in ("Alpha", "Gamma", "Beta", str(ATTEMPT)):
        assert expected in message


async def test_live_start_over_an_unsettled_rehearsal_order_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(in_flight=[_order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}")])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(dry_run=False, reader=reader)

    assert len(_errors(caplog)) == 1
    assert str(ATTEMPT) in _errors(caplog)[0].getMessage()


async def test_dry_run_start_over_an_unsettled_live_order_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(in_flight=[_order("8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10")])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(dry_run=True, reader=reader)

    assert len(_errors(caplog)) == 1
    assert str(ATTEMPT) in _errors(caplog)[0].getMessage()


async def test_an_unsettled_order_of_the_current_mode_starts_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(
            dry_run=True,
            reader=FakeReader(in_flight=[_order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}")]),
        )
        await assert_mode_matches_ledger(
            dry_run=False, reader=FakeReader(in_flight=[_order("1234567890123")])
        )

    assert caplog.records == []


# --- the ERROR reaches Telegram before the process exits ---------------------


class RecordingAlerter:
    """Stands in for ``TelegramAlerter``: no token, no network (rule 1)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.closed = False

    async def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))

    async def aclose(self) -> None:
        self.closed = True


async def test_the_refusal_reaches_the_alert_channel_before_the_context_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors ``worker.run``: the check runs INSIDE ``operator_alerts`` and its
    refusal propagates out of it. ``operator_alerts`` drains the bridge on the
    way out, so the alert is delivered although the process is about to die."""
    alerter = RecordingAlerter()
    monkeypatch.setattr(alerting, "build_alerter", lambda settings: alerter)
    settings = Settings(_env_file=None, alerts_enabled=True)  # type: ignore[call-arg]
    reader = FakeReader(opened=[_open(rehearsal=True, live=False)])

    with pytest.raises(StartupRefused):
        async with operator_alerts(settings) as bridge:
            assert bridge is not None
            await assert_mode_matches_ledger(dry_run=False, reader=reader)

    assert len(alerter.sent) == 1
    title, body = alerter.sent[0]
    assert "ERROR" in title
    for expected in ("Alpha", "bybit/usdt-m/USDT", "SOLUSDT.P", str(ALLOCATION), "then flip"):
        assert expected in body
    assert alerter.closed


async def test_a_clean_start_sends_no_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    alerter = RecordingAlerter()
    monkeypatch.setattr(alerting, "build_alerter", lambda settings: alerter)
    settings = Settings(_env_file=None, alerts_enabled=True)  # type: ignore[call-arg]

    async with operator_alerts(settings):
        await assert_mode_matches_ledger(dry_run=False, reader=FakeReader())

    assert alerter.sent == []
