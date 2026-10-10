"""Updating a strategy, and the move it refuses to make.

The refusal is the substance here. Switching a strategy between capital pools
routes the close of an open position to the wrong adapter, which leaves a real
holding open while the system believes it closed.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.update_strategy import (
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")
FIXED_NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)


def _strategy(**overrides: object) -> Strategy:
    policy = AllocationPolicy(exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        fill_mode=FillMode.PARTIAL,
        allocation_percent=AllocationPercent(Decimal("100")),
    )
    fields: dict[str, object] = {
        "id": STRATEGY_ID,
        "name": "BAT - RSI Divergences v1.3",
        "policy": policy,
        "enabled": False,
    }
    fields.update(overrides)
    return Strategy(**fields)  # type: ignore[arg-type]


class FakeRepository:
    def __init__(self, existing: Strategy | None) -> None:
        self.existing = existing
        self.updated: list[Strategy] = []

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        if self.existing is not None and self.existing.id == strategy_id:
            return self.existing
        return None

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        """The fake has no real row lock to take -- concurrency itself is
        proven only against real Postgres (tasks.md 2d.3,
        ``tests/strategies/infrastructure/test_update_strategy_concurrency.py``).
        This exists so ``UpdateStrategy`` can call the same port method it
        calls in production."""
        return await self.get_by_id(strategy_id)

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list_all(self) -> list[Strategy]:  # pragma: no cover
        return []

    async def update(self, strategy: Strategy) -> None:
        self.updated.append(strategy)
        # Persists for subsequent reads within the same test, the way a real
        # store would -- 2d.1's two sequential toggles depend on the SECOND
        # call seeing the FIRST call's write.
        self.existing = strategy


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class SpyEnablementLog:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, bool, datetime]] = []

    async def append(self, strategy_id: UUID, enabled: bool, occurred_at: datetime) -> None:
        self.calls.append((strategy_id, enabled, occurred_at))


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


def _build(
    existing: Strategy | None = None,
) -> tuple[UpdateStrategy, FakeRepository, SpyCommit, SpyEnablementLog, FixedClock]:
    repository = FakeRepository(_strategy() if existing is None else existing)
    commit = SpyCommit()
    log = SpyEnablementLog()
    clock = FixedClock(FIXED_NOW)
    return (
        UpdateStrategy(
            repository=repository,  # type: ignore[arg-type]
            commit=commit,  # type: ignore[arg-type]
            enablement_log=log,  # type: ignore[arg-type]
            clock=clock,  # type: ignore[arg-type]
        ),
        repository,
        commit,
        log,
        clock,
    )


def test_the_command_offers_no_way_to_change_the_pool() -> None:
    """Structural, and the most important test in this file. Moving a
    strategy between pools is not an edit: it is a different pool of money,
    and a switched strategy routes the close of an open position to the wrong
    adapter."""
    fields = set(UpdateCommand.__dataclass_fields__)

    assert "venue" not in fields
    assert "settlement_currency" not in fields


async def test_enabling_is_a_single_field_change() -> None:
    use_case, repository, commit, _, _ = _build()

    updated = await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))

    assert updated.enabled is True
    assert repository.updated[0].enabled is True
    assert commit.commits == 1


async def test_omitted_fields_are_left_exactly_as_they_were() -> None:
    """``None`` means unchanged, so a caller flipping one switch cannot
    silently reset the rest to defaults it never sent."""
    existing = _strategy(name="original", enabled=True)
    use_case, repository, _, _, _ = _build(existing)

    updated = await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("40"))
    )

    assert updated.name == "original"
    assert updated.enabled is True
    assert updated.policy.fill_mode is FillMode.PARTIAL
    assert updated.policy.allocation_percent.value == Decimal("40")
    assert repository.updated[0].policy.allocation_percent.value == Decimal("40")


async def test_the_pool_survives_every_update() -> None:
    """Belt and braces alongside the structural test: whatever else changes,
    the venue and settlement currency come out the other side untouched."""
    use_case, _, _, _, _ = _build()

    updated = await use_case.update(
        UpdateCommand(
            strategy_id=STRATEGY_ID,
            name="renamed",
            fill_mode=FillMode.SKIP,
            allocation_percent=Decimal("10"),
            enabled=True,
        )
    )

    assert updated.policy.venue is Venue.SPOT
    assert updated.policy.settlement_currency is Currency.USDT


async def test_disabling_stops_it_without_deleting_it() -> None:
    """The ledger keeps every fill this strategy ever produced, and PnL is a
    query over it. Turning a strategy off must not take its history with it."""
    use_case, _, _, _, _ = _build(_strategy(enabled=True))

    updated = await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, enabled=False)
    )

    assert updated.enabled is False
    assert updated.id == STRATEGY_ID


async def test_an_unregistered_id_is_refused_rather_than_created() -> None:
    use_case, repository, commit, _, _ = _build()

    with pytest.raises(UnknownStrategy, match="no strategy registered"):
        await use_case.update(UpdateCommand(strategy_id=uuid4(), enabled=True))

    assert repository.updated == []
    assert commit.commits == 0


async def test_an_invalid_percent_is_refused_by_the_domain() -> None:
    """``AllocationPercent`` enforces 0 < value <= 100, and the update path
    goes through it rather than around it."""
    from strategy_manager.shared.domain.errors import InvariantViolation

    use_case, repository, _, _, _ = _build()

    with pytest.raises(InvariantViolation):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("150"))
        )

    assert repository.updated == []


# --------------------------------------------------------------------------
# 2d.1 / 2d.2 -- the enablement log, wired
# --------------------------------------------------------------------------


async def test_toggling_enabled_twice_writes_two_events_same_transaction_as_enabled_write() -> (
    None
):
    """spec: strategy-lifecycle § "Enable/Disable Event Log" — "Toggling
    enabled twice writes two events: one disable event and one enable event,
    each in the same transaction as its enabled write." Each event append
    happens inside the SAME ``update()`` call as its own row write and its
    own commit -- there is exactly one commit per toggle, and the log call
    for that toggle happened before it."""
    use_case, _, commit, log, clock = _build(_strategy(enabled=True))

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))
    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))

    assert log.calls == [
        (STRATEGY_ID, False, clock.now()),
        (STRATEGY_ID, True, clock.now()),
    ]
    assert commit.commits == 2


async def test_noop_patch_setting_enabled_true_again_writes_no_event() -> None:
    """spec: "A PATCH that does not change the effective enabled value MUST
    write no event." The PATCH itself still succeeds and commits -- only the
    event write is skipped."""
    use_case, _, commit, log, _ = _build(_strategy(enabled=True))

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))

    assert log.calls == []
    assert commit.commits == 1


# --------------------------------------------------------------------------
# 12f.9.6 -- the INFO line of a changed share (design.md, unit 12f addendum,
# section J; spec: strategy-lifecycle "A Change Of A Strategy's Share Of The
# Pool Is Logged"). Only a REAL change writes it, after the commit, with the
# strategy id and the old and new value in plain notation.
# --------------------------------------------------------------------------

LOGGER = "strategy_manager.strategies.application.update_strategy"


def _share_lines(caplog: pytest.LogCaptureFixture) -> list[tuple[str, int, str]]:
    return [
        (record.name, record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == LOGGER
    ]


def _with_share(value: str, **overrides: object) -> Strategy:
    base = _strategy(**overrides)
    return replace(
        base,
        policy=replace(base.policy, allocation_percent=AllocationPercent(Decimal(value))),
    )


async def test_a_changed_share_logs_one_info_line_with_the_id_and_both_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case, _, _, _, _ = _build(_with_share("30"))

    with caplog.at_level(logging.DEBUG):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("33.5"))
        )

    assert _share_lines(caplog) == [
        (
            LOGGER,
            logging.INFO,
            f"strategy {STRATEGY_ID} share of the pool changed from 30 to 33.5",
        )
    ]


async def test_a_share_that_goes_below_one_is_logged_in_plain_notation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A tiny share must never be written as an exponent (``1E-7``)."""
    use_case, _, _, _, _ = _build(_with_share("100"))

    with caplog.at_level(logging.DEBUG):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("0.0000001"))
        )

    assert _share_lines(caplog) == [
        (
            LOGGER,
            logging.INFO,
            f"strategy {STRATEGY_ID} share of the pool changed from 100 to 0.0000001",
        )
    ]


async def test_the_same_value_written_differently_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """"Changed" is decided on the decimal value, not on its text: 33.5 over
    33.5 and 33.50 over 33.5 are not changes."""
    use_case, _, commit, _, _ = _build(_with_share("33.5"))

    with caplog.at_level(logging.DEBUG):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("33.5"))
        )
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("33.50"))
        )

    assert commit.commits == 2  # both updates ran; only the line is skipped
    assert _share_lines(caplog) == []


async def test_patching_another_field_logs_no_share_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case, _, commit, _, _ = _build(_with_share("30", enabled=False))

    with caplog.at_level(logging.DEBUG):
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"))

    assert commit.commits == 2
    assert _share_lines(caplog) == []


async def test_a_refused_update_logs_no_share_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Archived, a share the domain refuses, and an unknown id each raise before
    anything is written, and none writes a share line."""
    from strategy_manager.shared.domain.errors import InvariantViolation
    from strategy_manager.strategies.application.update_strategy import StrategyArchived

    archived, _, _, _, _ = _build(_with_share("30", archived_at=FIXED_NOW))
    refused, _, _, _, _ = _build(_with_share("30"))
    unknown, _, _, _, _ = _build(_with_share("30"))
    command = UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("33.5"))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StrategyArchived):
            await archived.update(command)
        with pytest.raises(InvariantViolation):
            await refused.update(
                UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("150"))
            )
        with pytest.raises(UnknownStrategy):
            await unknown.update(
                UpdateCommand(strategy_id=uuid4(), allocation_percent=Decimal("33.5"))
            )

    assert _share_lines(caplog) == []


async def test_a_failed_commit_logs_no_share_line(caplog: pytest.LogCaptureFixture) -> None:
    """The line is written after the commit, so a rolled-back change leaves no
    line that says it happened."""

    class FailingCommit:
        async def commit(self) -> None:
            raise RuntimeError("commit failed")

    use_case = UpdateStrategy(
        repository=FakeRepository(_with_share("30")),  # type: ignore[arg-type]
        commit=FailingCommit(),  # type: ignore[arg-type]
        enablement_log=SpyEnablementLog(),  # type: ignore[arg-type]
        clock=FixedClock(FIXED_NOW),  # type: ignore[arg-type]
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError, match="commit failed"):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("33.5"))
        )

    assert _share_lines(caplog) == []
