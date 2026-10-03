"""``DeleteStrategy``: the order of its steps, each refusal and its one log line,
the database backstop and the lock order (design.md addendum 9x, § D and § I;
tasks.md 9xc.2 and 9xc.6).

Fakes share ONE event log, so a test reads the order in which the use case
reached the repository, the pool lock, the history and the commit. What a lock
actually serializes is proven on real PostgreSQL in
``tests/strategies/infrastructure/test_delete_strategy_concurrency.py``.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.archive_strategy import StillEnabled
from strategy_manager.strategies.application.delete_strategy import (
    DeleteStrategy,
    StrategyHasHistory,
)
from strategy_manager.strategies.application.ports import (
    StrategyHistory,
    StrategyStillReferenced,
)
from strategy_manager.strategies.application.update_strategy import UnknownStrategy
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")
NAME = "Delete Me v1"
LOGGER = "strategy_manager.strategies.application.delete_strategy"

KINDS = [
    "signals",
    "reservations",
    "execution_attempts",
    "ledger_entries",
    "booking_proposals",
    "enablement_events",
]


def _strategy(**overrides: object) -> Strategy:
    policy = AllocationPolicy(
        exchange=Exchange.BYBIT,
        venue=Venue.USDT_M,
        settlement_currency=Currency.USDT,
        fill_mode=FillMode.PARTIAL,
        allocation_percent=AllocationPercent(Decimal("100")),
    )
    fields: dict[str, object] = {
        "id": STRATEGY_ID,
        "name": NAME,
        "policy": policy,
        "allowed_pairs": AllowedPairs(frozenset({"STXUSDT"})),
    }
    fields.update(overrides)
    return Strategy(**fields)  # type: ignore[arg-type]


def _history(**counts: int) -> StrategyHistory:
    base = dict.fromkeys(KINDS, 0)
    base.update(counts)
    return StrategyHistory(**base)


class FakeRepository:
    def __init__(
        self,
        unlocked: Strategy | None,
        events: list[str],
        locked: Strategy | None | str = "same",
        refuse_delete_with: StrategyStillReferenced | None = None,
    ) -> None:
        self.unlocked = unlocked
        self.locked = unlocked if locked == "same" else locked
        self.events = events
        self.refuse_delete_with = refuse_delete_with
        self.deleted: list[UUID] = []

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id")
        return self.unlocked

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id_for_update")
        return self.locked  # type: ignore[return-value]

    async def delete(self, strategy_id: UUID) -> None:
        self.events.append("delete")
        if self.refuse_delete_with is not None:
            raise self.refuse_delete_with
        self.deleted.append(strategy_id)

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:  # pragma: no cover
        return []

    async def update(self, strategy: Strategy) -> None:  # pragma: no cover
        raise AssertionError("DeleteStrategy must never update a strategy")


class FakePoolLock:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.acquired: list[tuple[str, str, str]] = []

    async def acquire(self, exchange: str, venue: str, settlement_currency: str) -> None:
        self.events.append("pool_lock")
        self.acquired.append((exchange, venue, settlement_currency))


class FakeHistory:
    def __init__(self, events: list[str], answer: StrategyHistory) -> None:
        self.events = events
        self.answer = answer

    async def history(self, strategy_id: UUID) -> StrategyHistory:
        self.events.append("history")
        return self.answer


class SpyCommit:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.commits = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1


class Harness:
    def __init__(
        self,
        unlocked: Strategy | None = None,
        *,
        locked: Strategy | None | str = "same",
        history: StrategyHistory | None = None,
        refuse_delete_with: StrategyStillReferenced | None = None,
    ) -> None:
        self.events: list[str] = []
        self.repository = FakeRepository(
            _strategy() if unlocked is None else unlocked,
            self.events,
            locked=locked,
            refuse_delete_with=refuse_delete_with,
        )
        self.pool_lock = FakePoolLock(self.events)
        self.history = FakeHistory(self.events, _history() if history is None else history)
        self.commit = SpyCommit(self.events)
        self.use_case = DeleteStrategy(
            repository=self.repository,
            pool_lock=self.pool_lock,
            history=self.history,
            commit=self.commit,
        )


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER]


async def test_an_unknown_id_raises_unknown_strategy_before_any_lock() -> None:
    harness = Harness()
    harness.repository.unlocked = None

    with pytest.raises(UnknownStrategy):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.events == ["get_by_id"]
    assert harness.pool_lock.acquired == []


async def test_the_pool_lock_is_taken_before_the_row_lock_and_history_is_read_after_both() -> None:
    harness = Harness()

    await harness.use_case.delete(STRATEGY_ID)

    assert harness.events == [
        "get_by_id",
        "pool_lock",
        "get_by_id_for_update",
        "history",
        "delete",
        "commit",
    ]


async def test_the_pool_locked_is_the_strategys_own_exchange_venue_and_settlement_currency() -> (
    None
):
    own = _strategy(
        policy=AllocationPolicy(
            exchange=Exchange.PIONEX,
            venue=Venue.COIN_M,
            settlement_currency=Currency.BTC,
            fill_mode=FillMode.PARTIAL,
            allocation_percent=AllocationPercent(Decimal("100")),
        )
    )
    harness = Harness(own)

    await harness.use_case.delete(STRATEGY_ID)

    assert harness.pool_lock.acquired == [("pionex", "coin-m", "BTC")]


async def test_a_row_gone_after_the_lock_raises_unknown_strategy() -> None:
    harness = Harness(locked=None)

    with pytest.raises(UnknownStrategy):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.events == ["get_by_id", "pool_lock", "get_by_id_for_update"]


async def test_an_enabled_strategy_is_refused_before_history_is_read() -> None:
    harness = Harness(_strategy(enabled=True))

    with pytest.raises(StillEnabled):
        await harness.use_case.delete(STRATEGY_ID)

    assert "history" not in harness.events
    assert harness.repository.deleted == []


async def test_enabled_is_decided_from_the_locked_read_not_the_unlocked_one() -> None:
    """Disabled at the unlocked read, enabled by the time the row lock is granted:
    a concurrent enable committed in between must be observed."""
    harness = Harness(_strategy(enabled=False), locked=_strategy(enabled=True))

    with pytest.raises(StillEnabled):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.events == ["get_by_id", "pool_lock", "get_by_id_for_update"]
    assert harness.repository.deleted == []


@pytest.mark.parametrize("kind", KINDS)
async def test_each_kind_of_history_alone_refuses_and_nothing_is_deleted(kind: str) -> None:
    harness = Harness(history=_history(**{kind: 1}))

    with pytest.raises(StrategyHasHistory) as raised:
        await harness.use_case.delete(STRATEGY_ID)

    assert raised.value.history.blocking() == {kind: 1}
    assert harness.repository.deleted == []
    assert "delete" not in harness.events


async def test_the_refusal_carries_all_six_counts() -> None:
    answered = _history(signals=3, reservations=2, ledger_entries=1, enablement_events=4)
    harness = Harness(history=answered)

    with pytest.raises(StrategyHasHistory) as raised:
        await harness.use_case.delete(STRATEGY_ID)

    assert raised.value.history == answered
    assert raised.value.constraint is None


async def test_no_history_deletes_and_commits_exactly_once() -> None:
    harness = Harness()

    await harness.use_case.delete(STRATEGY_ID)

    assert harness.repository.deleted == [STRATEGY_ID]
    assert harness.commit.commits == 1


async def test_a_database_refusal_becomes_has_history_and_logs_one_error_naming_the_constraint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(
        refuse_delete_with=StrategyStillReferenced("fk_strategy_enablement_events_strategy")
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER), pytest.raises(StrategyHasHistory) as raised:
        await harness.use_case.delete(STRATEGY_ID)

    assert raised.value.constraint == "fk_strategy_enablement_events_strategy"
    assert raised.value.history == _history()  # the counts as read: all zero
    assert harness.commit.commits == 0
    records = _records(caplog)
    assert [record.levelno for record in records] == [logging.ERROR]
    message = records[0].getMessage()
    assert "fk_strategy_enablement_events_strategy" in message
    assert str(STRATEGY_ID) in message
    assert repr(NAME) in message


async def test_a_successful_delete_logs_one_info_with_id_name_and_pool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness()

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await harness.use_case.delete(STRATEGY_ID)

    records = _records(caplog)
    assert [record.levelno for record in records] == [logging.INFO]
    message = records[0].getMessage()
    assert str(STRATEGY_ID) in message
    assert repr(NAME) in message
    assert "bybit/usdt-m/USDT" in message
    assert "archived=False" in message


def _refusal_harness(case: str) -> Harness:
    if case == "unknown":
        harness = Harness()
        harness.repository.unlocked = None
        return harness
    if case == "enabled":
        return Harness(_strategy(enabled=True))
    return Harness(history=_history(signals=2, ledger_entries=1))


@pytest.mark.parametrize("case", ["unknown", "enabled", "history"])
async def test_each_refusal_logs_exactly_one_warning(
    case: str, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _refusal_harness(case)

    with (
        caplog.at_level(logging.DEBUG, logger=LOGGER),
        pytest.raises((UnknownStrategy, StillEnabled, StrategyHasHistory)),
    ):
        await harness.use_case.delete(STRATEGY_ID)

    records = _records(caplog)
    assert [record.levelno for record in records] == [logging.WARNING]
    message = records[0].getMessage()
    assert str(STRATEGY_ID) in message
    if case != "unknown":
        assert repr(NAME) in message
    if case == "history":
        assert "signals=2" in message
        assert "ledger_entries=1" in message


@pytest.mark.parametrize("case", ["unknown", "enabled", "history"])
async def test_no_refusal_writes_or_commits_anything(case: str) -> None:
    harness = _refusal_harness(case)

    with pytest.raises((UnknownStrategy, StillEnabled, StrategyHasHistory)):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.repository.deleted == []
    assert harness.commit.commits == 0
    assert "delete" not in harness.events
    assert "commit" not in harness.events


# 9xc.6: Q3 answered "yes" (decision 42). An archived strategy is disabled by
# construction, so the history alone decides, and it is never un-archived.


async def test_an_archived_strategy_with_no_history_is_deleted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    archived = _strategy(archived_at=datetime(2026, 9, 1, tzinfo=UTC))
    harness = Harness(archived)

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.repository.deleted == [STRATEGY_ID]
    assert harness.commit.commits == 1
    records = _records(caplog)
    assert [record.levelno for record in records] == [logging.INFO]
    assert "archived=True" in records[0].getMessage()


async def test_an_archived_strategy_with_history_is_refused_has_history() -> None:
    archived = replace(_strategy(), archived_at=datetime(2026, 9, 1, tzinfo=UTC))
    harness = Harness(archived, history=_history(ledger_entries=1))

    with pytest.raises(StrategyHasHistory) as raised:
        await harness.use_case.delete(STRATEGY_ID)

    assert raised.value.history.blocking() == {"ledger_entries": 1}
    assert harness.repository.deleted == []
    assert harness.commit.commits == 0
