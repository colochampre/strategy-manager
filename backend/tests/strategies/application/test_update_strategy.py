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
from strategy_manager.strategies.application.ports import (
    AuthorHasNoDisplayName,
    StrategyExposure,
    SubscriberPool,
)
from strategy_manager.strategies.application.subscriber_locks import SubscribersChanged
from strategy_manager.strategies.application.update_strategy import (
    OpenPosition,
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.stop_loss import StopLossPct
from strategy_manager.strategies.domain.strategy import (
    AllocationPolicy,
    FillMode,
    Strategy,
    Visibility,
)
from tests.owner import OWNER_ID
from tests.strategies.author_names import FixedAuthorNames
from tests.strategies.fakes import (
    DisableGuard,
    FakeSubscribers,
    RecordingPoolLock,
    author_pool,
    disable_guard,
)

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")
FIXED_NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
LOGGER = "strategy_manager.strategies.application.update_strategy"
TOKEN = "t" * 43


def _strategy(**overrides: object) -> Strategy:
    policy = AllocationPolicy(exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        fill_mode=FillMode.PARTIAL,
    )
    fields: dict[str, object] = {
        "id": STRATEGY_ID,
        "name": "BAT - RSI Divergences v1.3",
        "policy": policy,
        "author_id": OWNER_ID,
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
    author_names: FixedAuthorNames | None = None,
    guard: DisableGuard | None = None,
) -> tuple[UpdateStrategy, FakeRepository, SpyCommit, SpyEnablementLog, FixedClock]:
    repository = FakeRepository(_strategy() if existing is None else existing)
    guard = guard or disable_guard(repository.existing)  # type: ignore[arg-type]
    commit = SpyCommit()
    log = SpyEnablementLog()
    clock = FixedClock(FIXED_NOW)
    return (
        UpdateStrategy(
            repository=repository,  # type: ignore[arg-type]
            commit=commit,  # type: ignore[arg-type]
            enablement_log=log,  # type: ignore[arg-type]
            clock=clock,  # type: ignore[arg-type]
            author_names=author_names or FixedAuthorNames(),
            **guard,
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


def test_the_command_offers_no_way_to_change_the_share() -> None:
    """C.4b: the share is the subscription's, and since 0033 the strategy has no
    copy of it."""
    assert "allocation_percent" not in UpdateCommand.__dataclass_fields__


async def test_a_strategy_does_not_turn_public_before_its_author_has_a_name() -> None:
    """Decision 27: the public list names the author, and it has nothing to name."""
    use_case, repository, commit, _, _ = _build(author_names=FixedAuthorNames(named=False))

    with pytest.raises(AuthorHasNoDisplayName):
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PUBLIC))

    assert repository.updated == []
    assert commit.commits == 0


async def test_a_strategy_turns_public_once_its_author_has_a_name() -> None:
    names = FixedAuthorNames()
    use_case, repository, commit, _, _ = _build(author_names=names)

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PUBLIC))

    assert repository.updated[0].visibility is Visibility.PUBLIC
    assert names.asked == [OWNER_ID]
    assert commit.commits == 1


@pytest.mark.parametrize(
    "command",
    [
        UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"),
        UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PUBLIC),
        UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PRIVATE),
    ],
)
async def test_a_strategy_already_public_is_not_refused_for_an_unnamed_author(
    command: UpdateCommand,
) -> None:
    """The rule acts on turning public (decision 27). The active strategies were
    public before any name existed, and they stay editable."""
    use_case, repository, commit, _, _ = _build(
        _strategy(visibility=Visibility.PUBLIC), FixedAuthorNames(named=False)
    )

    await use_case.update(command)

    assert len(repository.updated) == 1
    assert commit.commits == 1


@pytest.mark.parametrize(
    "command",
    [
        UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"),
        UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PRIVATE),
    ],
)
async def test_a_private_strategy_is_edited_with_no_name_at_all(command: UpdateCommand) -> None:
    use_case, repository, commit, _, _ = _build(author_names=FixedAuthorNames(named=False))

    await use_case.update(command)

    assert len(repository.updated) == 1
    assert commit.commits == 1


async def test_the_author_changes_the_level_and_nothing_else_changes() -> None:
    before = _strategy(name="kept", description="kept words")
    use_case, repository, commit, log, _ = _build(before)

    updated = await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal("7.5")))
    )

    assert updated.stop_loss_pct == StopLossPct(Decimal("7.5"))
    assert repository.updated == [updated]
    assert updated == replace(before, stop_loss_pct=StopLossPct(Decimal("7.5")))
    assert commit.commits == 1
    assert log.calls == []


async def test_an_update_that_names_no_level_leaves_the_level_as_it_is() -> None:
    use_case, repository, _, _, _ = _build(_strategy(stop_loss_pct=StopLossPct(Decimal("15"))))

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"))

    assert repository.updated[0].stop_loss_pct == StopLossPct(Decimal("15"))


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
        UpdateCommand(strategy_id=STRATEGY_ID, fill_mode=FillMode.SKIP)
    )

    assert updated.name == "original"
    assert updated.enabled is True
    assert updated.policy.fill_mode is FillMode.SKIP
    assert repository.updated[0].policy.fill_mode is FillMode.SKIP


async def test_the_pool_survives_every_update() -> None:
    """Belt and braces alongside the structural test: whatever else changes,
    the venue and settlement currency come out the other side untouched."""
    use_case, _, _, _, _ = _build()

    updated = await use_case.update(
        UpdateCommand(
            strategy_id=STRATEGY_ID,
            name="renamed",
            fill_mode=FillMode.SKIP,
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


# --- the log of a link (K.D advisory A3) ------------------------------------------


@pytest.mark.parametrize(
    ("held", "asked", "said"),
    [
        (Visibility.PRIVATE, Visibility.LINK, "made"),
        (Visibility.PUBLIC, Visibility.LINK, "made"),
        (Visibility.LINK, Visibility.PRIVATE, "killed"),
        (Visibility.LINK, Visibility.PUBLIC, "killed"),
    ],
)
async def test_a_link_made_or_killed_is_said_at_info_naming_the_strategy_never_the_token(
    held: Visibility, asked: Visibility, said: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Whoever holds a link opens the strategy, so when one began or stopped working
    must be answerable from the log; a link killed and made again is a rotation."""
    existing = _strategy(visibility=held, share_token=TOKEN if held is Visibility.LINK else None)
    use_case, repository, _, _, _ = _build(existing)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, visibility=asked))

    lines = [each for each in caplog.records if each.name == LOGGER]
    assert [each.levelno for each in lines] == [logging.INFO]
    line = lines[0].getMessage()
    assert f"link {said}" in line
    assert str(STRATEGY_ID) in line and str(OWNER_ID) in line
    assert TOKEN not in line
    token = repository.updated[0].share_token
    assert token is None or token not in line


@pytest.mark.parametrize(
    ("held", "command"),
    [
        (Visibility.LINK, UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.LINK)),
        (Visibility.LINK, UpdateCommand(strategy_id=STRATEGY_ID, name="renamed")),
        (Visibility.PRIVATE, UpdateCommand(strategy_id=STRATEGY_ID, visibility=Visibility.PUBLIC)),
    ],
)
async def test_an_update_that_neither_makes_nor_kills_a_link_says_nothing_of_one(
    held: Visibility, command: UpdateCommand, caplog: pytest.LogCaptureFixture
) -> None:
    existing = _strategy(visibility=held, share_token=TOKEN if held is Visibility.LINK else None)
    use_case, _, _, _, _ = _build(existing)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await use_case.update(command)

    assert [each for each in caplog.records if each.name == LOGGER] == []


# --- the disable guard (subscriber-safety SS.8a) ---------------------------------

HELD = StrategyExposure(
    symbols=frozenset({"STXUSDT"}),
    allocations=(UUID("11111111-1111-4111-8111-111111111111"),),
    live_reservations=(),
    in_flight_attempts=(),
)


async def test_disabling_a_strategy_that_holds_exposure_is_refused_and_writes_nothing() -> None:
    guard = disable_guard(_strategy(enabled=True), HELD)
    use_case, repository, commit, log, _ = _build(_strategy(enabled=True), guard=guard)

    with pytest.raises(OpenPosition, match="STXUSDT") as refused:
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))

    assert refused.value.exposure == HELD
    assert repository.updated == []  # the strategy stays enabled
    assert repository.existing is not None and repository.existing.enabled is True
    assert log.calls == []  # no event for a disable that did not happen
    assert commit.commits == 0


async def test_disabling_a_flat_strategy_takes_the_subscribers_pool_locks_first() -> None:
    strategy = _strategy(enabled=True)
    guard = disable_guard(strategy)
    use_case, _, commit, log, clock = _build(strategy, guard=guard)

    updated = await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))

    assert updated.enabled is False
    assert log.calls == [(STRATEGY_ID, False, clock.now())]
    assert commit.commits == 1
    assert guard["exposure"].asked == 1
    assert guard["pool_lock"].acquired == [(OWNER_ID, "pionex", "spot", "USDT")]


async def test_enabling_never_asks_for_exposure_nor_takes_a_pool_lock() -> None:
    guard = disable_guard(_strategy(), HELD)
    use_case, repository, _, _, _ = _build(guard=guard)

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))

    assert repository.updated[0].enabled is True
    assert guard["exposure"].asked == 0
    assert guard["pool_lock"].acquired == []


async def test_editing_other_fields_of_an_enabled_strategy_takes_today_s_path() -> None:
    guard = disable_guard(_strategy(enabled=True), HELD)
    use_case, repository, _, log, _ = _build(_strategy(enabled=True), guard=guard)

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"))

    assert repository.updated[0].name == "renamed"
    assert log.calls == []
    assert guard["exposure"].asked == 0
    assert guard["pool_lock"].acquired == []


async def test_editing_a_disabled_strategy_that_still_holds_exposure_is_allowed() -> None:
    """Exposure on a stopped strategy is the sweep's business (SS.8b), not a
    reason to freeze its other fields."""
    guard = disable_guard(_strategy(), HELD)
    use_case, repository, _, _, _ = _build(guard=guard)

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"))

    assert repository.updated[0].name == "renamed"
    assert guard["exposure"].asked == 0


async def test_disabling_an_already_disabled_strategy_is_not_refused_for_exposure() -> None:
    """Nothing is turned off, so there is nothing to refuse: the exposure is read
    only when the row under the lock is still enabled."""
    guard = disable_guard(_strategy(), HELD)
    use_case, _, _, log, _ = _build(guard=guard)

    updated = await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))

    assert updated.enabled is False
    assert log.calls == []
    assert guard["exposure"].asked == 0


async def test_a_refused_disable_is_logged_naming_who_holds_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard = disable_guard(_strategy(enabled=True), HELD)
    use_case, _, _, _, _ = _build(_strategy(enabled=True), guard=guard)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(OpenPosition):
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))

    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        f"strategy disable refused, it still holds exposure: id={STRATEGY_ID} "
        "name='BAT - RSI Divergences v1.3' held_by=[]"
    ]


async def test_a_subscriber_who_joins_during_a_disable_refuses_it_and_writes_nothing() -> None:
    strategy = _strategy(enabled=True)
    joined = SubscriberPool(
        pool_id=2, user_id=uuid4(), pool=("pionex", "spot", "USDT")
    )
    guard = disable_guard(strategy)
    guard["subscribers"] = FakeSubscribers([author_pool(strategy)], [author_pool(strategy), joined])
    use_case, repository, commit, log, _ = _build(strategy, guard=guard)

    with pytest.raises(SubscribersChanged, match="while it was being disabled"):
        await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=False))

    assert repository.updated == []
    assert log.calls == []
    assert commit.commits == 0
    assert guard["exposure"].asked == 0


# --- a stop widened under seats above its new cap (panel-redesign RD.9a) ----------------------


def _stop_change(
    *, was: str, lowered: int = 0
) -> tuple[UpdateStrategy, FakeRepository, SpyCommit, DisableGuard, list[str]]:
    """A strategy at ``was`` percent and a use case whose subscribers lower ``lowered``
    seats; ``events`` is the order the seats, the row and the commit were touched in."""
    events: list[str] = []
    strategy = _strategy(stop_loss_pct=StopLossPct(Decimal(was)))
    repository = FakeRepository(strategy)
    guard = disable_guard(strategy)
    guard["subscribers"] = FakeSubscribers.sole_author(strategy, events=events, lowered=lowered)
    guard["pool_lock"] = RecordingPoolLock(events)
    commit = SpyCommit()
    use_case = UpdateStrategy(
        repository=repository,  # type: ignore[arg-type]
        commit=commit,  # type: ignore[arg-type]
        enablement_log=SpyEnablementLog(),  # type: ignore[arg-type]
        clock=FixedClock(FIXED_NOW),  # type: ignore[arg-type]
        author_names=FixedAuthorNames(),
        **guard,
    )
    return use_case, repository, commit, guard, events


async def test_a_widened_stop_lowers_the_seats_above_its_new_cap_to_that_cap() -> None:
    use_case, repository, commit, guard, _ = _stop_change(was="10", lowered=2)

    await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal("20")))
    )

    # 100 / (20 + 1) is 4.76: the cap of a 20 percent stop is 4x.
    assert guard["subscribers"].lowered == [(STRATEGY_ID, 4, FIXED_NOW)]  # type: ignore[attr-defined]
    assert repository.updated[0].stop_loss_pct == StopLossPct(Decimal("20"))
    assert commit.commits == 1


async def test_the_seats_are_lowered_under_the_pool_locks_and_the_row_before_the_commit() -> None:
    use_case, _, _, _, events = _stop_change(was="10", lowered=1)

    await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal("20")))
    )

    assert events == ["live_pools", "pool_lock", "live_pools", "lower_above"]


@pytest.mark.parametrize("to", ["10", "5", "9.5"])
async def test_a_stop_that_leaves_the_cap_or_raises_it_lowers_nothing(to: str) -> None:
    # 10 percent is 9x; 5 percent is 16x; 9.5 percent is 9x again (100 / 10.5).
    use_case, repository, _, guard, _ = _stop_change(was="10")

    await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal(to)))
    )

    assert guard["subscribers"].lowered == []  # type: ignore[attr-defined]
    assert repository.updated[0].stop_loss_pct == StopLossPct(Decimal(to))


async def test_a_request_that_names_no_stop_takes_no_lock_and_lowers_nothing() -> None:
    use_case, _, _, guard, events = _stop_change(was="10")

    await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, name="renamed"))

    assert guard["subscribers"].lowered == []  # type: ignore[attr-defined]
    assert events == []


async def test_a_failure_while_lowering_commits_nothing_and_writes_no_stop() -> None:
    use_case, repository, commit, guard, _ = _stop_change(was="10", lowered=1)

    async def fails(strategy_id: UUID, cap: int, now: datetime) -> int:
        raise RuntimeError("the seats could not be written")

    guard["subscribers"].lower_above = fails  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal("20")))
        )

    assert commit.commits == 0
    assert repository.updated == []


async def test_the_log_line_of_a_changed_stop_names_how_many_seats_were_lowered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case, _, _, _, _ = _stop_change(was="10", lowered=3)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, stop_loss_pct=StopLossPct(Decimal("20")))
        )

    [record] = [r for r in caplog.records if "stop level changed" in r.getMessage()]
    assert "seats_lowered=3" in record.getMessage()
