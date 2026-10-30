"""Decision 28 and AD7: the startup use case. It logs ONE ERROR naming every
offender and then refuses to start; when nothing offends it says nothing at all.

The reader is a fake here, the SQL is proven on real PostgreSQL elsewhere.
What this file adds is the property that makes the guard worth having: the
ERROR reaches the operator's Telegram before the process exits.
"""

import logging
from collections.abc import Collection, Sequence
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
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from strategy_manager.shared.infrastructure import alerting
from strategy_manager.shared.infrastructure.alerting import operator_alerts

ALLOCATION = UUID("aaaaaaaa-1111-2222-3333-444444444444")
ATTEMPT = UUID("bbbbbbbb-1111-2222-3333-444444444444")
USER = UUID("cccccccc-1111-2222-3333-444444444444")


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


class FakeKeys:
    def __init__(self, *keys: tuple[UUID, str]) -> None:
        self._keys = keys

    async def trade_capable_keys(self) -> Collection[tuple[UUID, str]]:
        return self._keys


#: Every real position in this file has a key that can close it, unless a test
#: is about the one that has not.
KEYS = FakeKeys((USER, "bybit"))


def _open(
    *, mode: Mode, rehearsal: bool = False, live: bool = False, name: str = "Alpha"
) -> OpenAllocationOrigin:
    return OpenAllocationOrigin(
        allocation_id=ALLOCATION if name == "Alpha" else uuid4(),
        user_id=USER,
        mode=mode,
        strategy_name=name,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="SOLUSDT.P",
        holds_rehearsal_fill=rehearsal,
        holds_live_fill=live,
    )


def _order(order_id: str, mode: Mode) -> InFlightAttemptOrigin:
    return InFlightAttemptOrigin(
        attempt_id=ATTEMPT,
        mode=mode,
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


async def test_a_live_record_over_rehearsal_fills_logs_one_error_and_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(opened=[_open(mode=Mode.LIVE, rehearsal=True)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    for expected in ("Alpha", "bybit/usdt-m/USDT", "SOLUSDT.P", str(ALLOCATION)):
        assert expected in message
    assert "recorded LIVE" in message


# --- 6d.2 -----------------------------------------------------------------


async def test_a_simulated_record_over_live_fills_logs_one_error_and_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(opened=[_open(mode=Mode.SIMULATION, live=True)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "Alpha" in message
    assert "recorded SIMULATION" in message
    assert "still be open on the venue" in message


# --- 6d.3 -----------------------------------------------------------------


async def test_nothing_open_starts_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(reader=FakeReader(), keys=FakeKeys())

    assert caplog.records == []


async def test_positions_in_both_modes_agreeing_with_their_records_start_and_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real position and a simulated one, side by side: what decisions 14 and 26
    make normal, and a state one ``DRY_RUN`` value could never have accepted."""
    reader = FakeReader(
        opened=[
            _open(mode=Mode.LIVE, live=True),
            _open(mode=Mode.SIMULATION, rehearsal=True, name="Gamma"),
        ]
    )

    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    assert caplog.records == []


# --- both kinds, every offender, in-flight orders ---------------------------


async def test_an_allocation_holding_both_kinds_refuses_whatever_it_recorded() -> None:
    for mode in Mode:
        reader = FakeReader(opened=[_open(mode=mode, rehearsal=True, live=True)])

        with pytest.raises(StartupRefused):
            await assert_mode_matches_ledger(reader=reader, keys=KEYS)


async def test_one_error_names_every_offender_not_one_error_each(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(
        opened=[
            _open(mode=Mode.LIVE, rehearsal=True, name="Alpha"),
            _open(mode=Mode.LIVE, rehearsal=True, name="Gamma"),
        ],
        in_flight=[_order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}", Mode.LIVE)],
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    for expected in ("Alpha", "Gamma", "Beta", str(ATTEMPT)):
        assert expected in message


async def test_a_live_record_over_an_unsettled_rehearsal_order_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(in_flight=[_order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}", Mode.LIVE)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    assert len(_errors(caplog)) == 1
    assert str(ATTEMPT) in _errors(caplog)[0].getMessage()


async def test_a_simulated_record_over_an_unsettled_live_order_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(
        in_flight=[_order("8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10", Mode.SIMULATION)]
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    assert len(_errors(caplog)) == 1
    assert str(ATTEMPT) in _errors(caplog)[0].getMessage()


async def test_unsettled_orders_agreeing_with_their_records_start_and_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(
        in_flight=[
            _order(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}", Mode.SIMULATION),
            _order("1234567890123", Mode.LIVE),
        ]
    )

    with caplog.at_level(logging.DEBUG):
        await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    assert caplog.records == []


# --- a real position needs a key that can close it (AD7) ------------------------


async def test_a_real_position_with_no_key_logs_one_error_and_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(opened=[_open(mode=Mode.LIVE, live=True)])

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused) as refused:
        await assert_mode_matches_ledger(reader=reader, keys=FakeKeys())

    errors = _errors(caplog)
    assert len(errors) == 1
    assert f"user {USER}: 1 allocation(s) on bybit" in errors[0].getMessage()
    assert refused.value.logged is True


async def test_a_mismatch_and_a_missing_key_share_the_one_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeReader(
        opened=[
            _open(mode=Mode.LIVE, live=True),
            _open(mode=Mode.LIVE, rehearsal=True, name="Gamma"),
        ]
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await assert_mode_matches_ledger(reader=reader, keys=FakeKeys())

    errors = _errors(caplog)
    assert len(errors) == 1
    assert "Gamma" in errors[0].getMessage()
    assert f"user {USER}: 2 allocation(s) on bybit" in errors[0].getMessage()


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
    reader = FakeReader(opened=[_open(mode=Mode.LIVE, rehearsal=True)])

    with pytest.raises(StartupRefused):
        async with operator_alerts(settings) as bridge:
            assert bridge is not None
            await assert_mode_matches_ledger(reader=reader, keys=KEYS)

    assert len(alerter.sent) == 1
    title, body = alerter.sent[0]
    assert "ERROR" in title
    for expected in ("Alpha", "bybit/usdt-m/USDT", "SOLUSDT.P", str(ALLOCATION), "by hand"):
        assert expected in body
    assert alerter.closed


async def test_a_clean_start_sends_no_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    alerter = RecordingAlerter()
    monkeypatch.setattr(alerting, "build_alerter", lambda settings: alerter)
    settings = Settings(_env_file=None, alerts_enabled=True)  # type: ignore[call-arg]

    async with operator_alerts(settings):
        await assert_mode_matches_ledger(reader=FakeReader(), keys=FakeKeys())

    assert alerter.sent == []
