"""``AnnounceNeedsOwner`` -- one ERROR record for the confirmed discrepancies
that need the owner, and a daily reminder under its own template (spec
"Confirmed Discrepancies Needing The Owner Are Announced" and "A Daily Reminder
Repeats What Still Needs The Owner"; design.md PR 15 addendum § E; owner
decision 66 Q3 and Q4, 2026-10-16; requirement R19: no quantity, price or fee
in an alert).
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application import announce_needs_owner as module
from strategy_manager.reconciliation.application.announce_needs_owner import (
    AnnounceNeedsOwner,
    reset_announcements,
)
from strategy_manager.reconciliation.application.ports import (
    DiscrepancyRecord,
    PoolKey,
)
from strategy_manager.reconciliation.domain.booking import BOOKING_REFUSAL_PHRASES, BookingRefusal
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)

T0 = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
GRACE = 300
REMINDER = 86400

ANNOUNCEMENT_TEMPLATE = "confirmed discrepancies need the owner: %s"
REMINDER_TEMPLATE = "reminder: %d confirmed discrepancies still need the owner: %s"

# Quantities that must never reach a record (R19): distinctive on purpose.
VENUE_NET = Decimal("123.456")
LEDGER_NET = Decimal("654.321")


class MutableClock:
    def __init__(self, now: datetime = T0) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


def _row(
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    confirmed_ago: int = GRACE + 60,
    allocations: int = 1,
    symbol: str = "STXUSDT",
    status: DiscrepancyStatus = DiscrepancyStatus.CONFIRMED,
) -> DiscrepancyRecord:
    return DiscrepancyRecord(
        id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        kind=kind,
        venue_net_base=VENUE_NET,
        ledger_net_base=LEDGER_NET,
        open_allocation_ids=tuple(uuid4() for _ in range(allocations)),
        consecutive_scans=2,
        status=status,
        first_observed_at=T0 - timedelta(seconds=confirmed_ago + 30),
        last_observed_at=T0,
        confirmed_at=T0 - timedelta(seconds=confirmed_ago),
        resolved_at=None,
        first_scan_id=uuid4(),
        last_scan_id=uuid4(),
        resolved_by_scan_id=None,
    )


class FakeDiscrepancies:
    def __init__(self, rows: Sequence[DiscrepancyRecord] = ()) -> None:
        self.rows = list(rows)

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]:
        assert status is DiscrepancyStatus.CONFIRMED and open_only
        return list(self.rows)


class FakeApproved:
    def __init__(self) -> None:
        self.by_discrepancy: dict[UUID, list[Observation]] = {}

    async def approved_observations(
        self, discrepancy_ids: Sequence[UUID]
    ) -> Mapping[UUID, Sequence[Observation]]:
        return {i: self.by_discrepancy[i] for i in discrepancy_ids if i in self.by_discrepancy}


class Harness:
    def __init__(self, rows: Sequence[DiscrepancyRecord] = ()) -> None:
        self.discrepancies = FakeDiscrepancies(rows)
        self.approved = FakeApproved()
        self.clock = MutableClock()
        self.reasons: dict[UUID, BookingRefusal] = {}
        self.use_case = AnnounceNeedsOwner(
            discrepancies=self.discrepancies,  # type: ignore[arg-type]
            approved=self.approved,
            clock=self.clock,
            grace_seconds=GRACE,
            reminder_seconds=REMINDER,
        )

    async def run(self) -> None:
        await self.use_case.run(self.reasons)


@pytest.fixture(autouse=True)
def _nothing_announced() -> None:
    """The memory of what was announced is process-wide; no test inherits it."""

    reset_announcements()


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# --- The announcement (cd.1.17) ---------------------------------------------


async def test_two_new_items_are_announced_in_one_error_with_reason_phrase_and_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unbooked = _row(kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION, symbol="STXUSDT")
    ambiguous = _row(kind=DiscrepancyKind.NO_MATCHING_ALLOCATION, symbol="SOLUSDT")
    harness = Harness([unbooked, ambiguous])
    harness.reasons[unbooked.id] = BookingRefusal.SUM_MISMATCH  # this run's sweep

    with caplog.at_level(logging.DEBUG):
        await harness.run()

    errors = _errors(caplog)
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert str(unbooked.id) in message and str(ambiguous.id) in message
    assert "STXUSDT" in message and "SOLUSDT" in message
    assert "ATTRIBUTABLE_SINGLE_ALLOCATION" in message and "NO_MATCHING_ALLOCATION" in message
    assert "bybit" in message and "usdt-m" in message and "USDT" in message
    assert "SUM_MISMATCH" in message
    assert BOOKING_REFUSAL_PHRASES[BookingRefusal.SUM_MISMATCH] in message
    assert "NOT_BOOKABLE" in message


async def test_not_bookable_names_the_kind_inside_its_own_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design § E: "``NOT_BOOKABLE`` with the kind"."""

    row = _row(kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE)

    with caplog.at_level(logging.DEBUG):
        await Harness([row]).run()

    assert (
        "NOT_BOOKABLE (the venue difference is of a kind this system never books: "
        "AMBIGUOUS_PARTIAL_REDUCE)"
    ) in _errors(caplog)[0].getMessage()


async def test_a_row_with_several_allocations_carries_its_own_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row(allocations=2, confirmed_ago=10)  # inside the grace: rule 3 still fires
    harness = Harness([row])

    with caplog.at_level(logging.DEBUG):
        await harness.run()

    errors = _errors(caplog)
    assert len(errors) == 1
    assert "SEVERAL_ALLOCATIONS" in errors[0].getMessage()


async def test_a_reason_unknown_to_the_process_is_announced_as_reason_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row()  # confirmed past the grace, nothing known about why
    harness = Harness([row])

    with caplog.at_level(logging.DEBUG):
        await harness.run()

    errors = _errors(caplog)
    assert len(errors) == 1, "an unexplained item is never left out of the announcement"
    message = errors[0].getMessage()
    assert "REASON_UNKNOWN" in message
    assert "see the worker log" in message
    assert str(row.id) in message


async def test_nothing_is_announced_on_a_second_run(caplog: pytest.LogCaptureFixture) -> None:
    harness = Harness([_row()])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        caplog.clear()
        await harness.run()

    assert _errors(caplog) == []


async def test_an_item_is_announced_again_after_it_was_dropped_and_returns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row()
    harness = Harness([row])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        assert len(_errors(caplog)) == 1
        caplog.clear()

        harness.discrepancies.rows = []  # it resolved itself
        await harness.run()
        assert _errors(caplog) == []

        harness.discrepancies.rows = [row]  # and it recurs
        await harness.run()

    assert len(_errors(caplog)) == 1


async def test_an_item_that_is_no_longer_needs_owner_is_dropped_from_the_announced_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Booked in between (an approved observation matches the row's current
    one), then unbooked again: the recurrence is announced anew."""

    row = _row()
    harness = Harness([row])
    with caplog.at_level(logging.DEBUG):
        await harness.run()
        caplog.clear()

        harness.approved.by_discrepancy[row.id] = [
            Observation(row.kind, row.venue_net_base, row.ledger_net_base)
        ]
        await harness.run()
        assert _errors(caplog) == []

        harness.approved.by_discrepancy.clear()
        await harness.run()

    assert len(_errors(caplog)) == 1


async def test_two_announcements_with_different_reasons_share_one_record_msg(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first, second = _row(), _row()
    harness = Harness([first])
    harness.reasons[first.id] = BookingRefusal.SUM_MISMATCH

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        harness.discrepancies.rows = [first, second]
        harness.reasons[second.id] = BookingRefusal.GROWS_OR_FLIPS
        await harness.run()

    errors = _errors(caplog)
    assert len(errors) == 2
    assert errors[0].msg == errors[1].msg == ANNOUNCEMENT_TEMPLATE
    assert errors[0].getMessage() != errors[1].getMessage()
    assert len(errors[0].args or ()) == 1, "the whole list is the template's one argument"


async def test_the_logger_is_not_under_the_alerts_namespace() -> None:
    assert not module.logger.name.startswith("strategy_manager.alerts")
    assert module.logger.name.startswith("strategy_manager.reconciliation")


async def test_the_record_holds_no_quantity_price_or_fee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row()
    harness = Harness([row])

    with caplog.at_level(logging.DEBUG):
        await harness.run()

    for record in caplog.records:
        text = record.getMessage()
        assert str(VENUE_NET) not in text and str(LEDGER_NET) not in text
        assert "123" not in text.replace(str(row.id), "")
        assert "654" not in text.replace(str(row.id), "")


async def test_an_automatic_booking_logs_nothing_above_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    being_booked = _row(confirmed_ago=10)
    booked = _row()
    harness = Harness([being_booked, booked])
    harness.approved.by_discrepancy[booked.id] = [
        Observation(booked.kind, booked.venue_net_base, booked.ledger_net_base)
    ]

    with caplog.at_level(logging.DEBUG):
        await harness.run()

    assert [r for r in caplog.records if r.levelno > logging.INFO] == []


async def test_the_memory_of_reasons_forgets_a_discrepancy_that_is_no_longer_open() -> None:
    gone, kept = uuid4(), _row()
    harness = Harness([kept])
    harness.reasons[gone] = BookingRefusal.SUM_MISMATCH
    harness.reasons[kept.id] = BookingRefusal.GROWS_OR_FLIPS

    await harness.run()

    assert harness.reasons == {kept.id: BookingRefusal.GROWS_OR_FLIPS}


# --- The daily reminder (cd.1.19) --------------------------------------------


def _reminders(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in _errors(caplog) if str(r.msg).startswith("reminder:")]


async def test_the_reminder_fires_after_the_interval_under_its_own_template(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row()
    harness = Harness([row])
    harness.reasons[row.id] = BookingRefusal.SUM_MISMATCH

    with caplog.at_level(logging.DEBUG):
        await harness.run()  # the announcement
        caplog.clear()
        harness.clock.current = T0 + timedelta(seconds=REMINDER)
        await harness.run()

    errors = _errors(caplog)
    assert len(errors) == 1
    assert errors[0].msg == REMINDER_TEMPLATE
    assert errors[0].msg != ANNOUNCEMENT_TEMPLATE, "else the throttle folds it away"
    assert errors[0].args is not None and errors[0].args[0] == 1
    assert "SUM_MISMATCH" in errors[0].getMessage()
    assert str(row.id) in errors[0].getMessage()


async def test_the_reminder_lists_everything_that_still_needs_the_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first, second = _row(), _row(kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE)
    harness = Harness([first])

    with caplog.at_level(logging.DEBUG):
        await harness.run()  # announces first
        harness.discrepancies.rows = [first, second]
        harness.clock.current = T0 + timedelta(seconds=REMINDER // 2)
        await harness.run()  # announces second alone
        caplog.clear()
        harness.clock.current = T0 + timedelta(seconds=REMINDER + REMINDER // 2)
        await harness.run()

    reminders = _reminders(caplog)
    assert len(reminders) == 1
    assert reminders[0].args is not None and reminders[0].args[0] == 2
    assert str(first.id) in reminders[0].getMessage()
    assert str(second.id) in reminders[0].getMessage()


async def test_the_reminder_does_not_fire_early(caplog: pytest.LogCaptureFixture) -> None:
    harness = Harness([_row()])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        caplog.clear()
        harness.clock.current = T0 + timedelta(seconds=REMINDER - 1)
        await harness.run()

    assert _errors(caplog) == []


async def test_the_reminder_does_not_fire_when_nothing_needs_the_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = _row()
    harness = Harness([row])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        caplog.clear()
        harness.discrepancies.rows = []
        harness.clock.current = T0 + timedelta(seconds=REMINDER * 3)
        await harness.run()

    assert _errors(caplog) == []


async def test_the_reminder_is_timed_from_the_last_notice_not_from_the_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness([_row()])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        harness.clock.current = T0 + timedelta(seconds=REMINDER)
        await harness.run()  # first reminder
        caplog.clear()
        harness.clock.current = T0 + timedelta(seconds=REMINDER * 2 - 1)
        await harness.run()  # one interval from the START, not from the reminder
        assert _errors(caplog) == []
        harness.clock.current = T0 + timedelta(seconds=REMINDER * 2)
        await harness.run()

    assert len(_reminders(caplog)) == 1


async def test_a_new_announcement_restarts_the_reminder_clock(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first, second = _row(), _row()
    harness = Harness([first])

    with caplog.at_level(logging.DEBUG):
        await harness.run()
        harness.discrepancies.rows = [first, second]
        harness.clock.current = T0 + timedelta(seconds=REMINDER - 10)
        await harness.run()  # announces second, restarting the clock
        caplog.clear()
        harness.clock.current = T0 + timedelta(seconds=REMINDER + 10)
        await harness.run()

    assert _errors(caplog) == []
