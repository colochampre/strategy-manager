"""``ReplaceAllowedPairs``: replacing a strategy's entire allowed-pairs list
as a unit, normalized through ``market_key()`` (design.md § 6
"Normalization"; spec: strategy-lifecycle; tasks.md 2e.2).
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
)
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs, EmptyAllowedPairs
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
    PairsChangedConcurrently,
    UnknownPairs,
)
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")


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
        "allowed_pairs": AllowedPairs(frozenset({"ETHUSDT"})),
    }
    fields.update(overrides)
    return Strategy(**fields)  # type: ignore[arg-type]


class FakeRepository:
    """``events`` is one log shared with the catalogue and the commit spy, so a
    test can read the ORDER the use case called them in. ``between_reads`` runs
    when the row lock is requested, which is how a test plays "another
    transaction committed after the unlocked read"."""

    def __init__(
        self,
        existing: Strategy | None,
        events: list[str] | None = None,
        between_reads: Callable[["FakeRepository"], None] | None = None,
    ) -> None:
        self.existing = existing
        self.updated: list[Strategy] = []
        self.events = events if events is not None else []
        self.between_reads = between_reads

    def _find(self, strategy_id: UUID) -> Strategy | None:
        if self.existing is not None and self.existing.id == strategy_id:
            return self.existing
        return None

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id")
        return self._find(strategy_id)

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id_for_update")
        if self.between_reads is not None:
            self.between_reads(self)
        return self._find(strategy_id)

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:  # pragma: no cover
        return []

    async def update(self, strategy: Strategy) -> None:
        self.events.append("update")
        self.updated.append(strategy)
        self.existing = strategy


class SpyCommit:
    def __init__(self, events: list[str] | None = None) -> None:
        self.commits = 0
        self.events = events if events is not None else []

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1


class FakeCatalog:
    """A fake ``PairCatalogPort``. It records the pool of every call, and fails
    with ``failure`` when one is given. The default list holds every symbol the
    older tests in this file add, so they run unchanged."""

    def __init__(
        self,
        available: frozenset[str] = frozenset({"ETHUSDT", "SOLUSDT"}),
        failure: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.available = available
        self.failure = failure
        self.asked: list[PoolKey] = []
        self.events = events if events is not None else []

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.events.append("catalogue")
        self.asked.append(pool)
        if self.failure is not None:
            raise self.failure
        return self.available


def _build(
    existing: Strategy | None = None,
    catalog: FakeCatalog | None = None,
    events: list[str] | None = None,
    between_reads: Callable[[FakeRepository], None] | None = None,
) -> tuple[ReplaceAllowedPairs, FakeRepository, SpyCommit]:
    """``events`` must be the SAME list the ``catalog`` was built with when a test
    reads the call order; otherwise each fake keeps its own."""
    log = events if events is not None else []
    repository = FakeRepository(
        _strategy() if existing is None else existing, log, between_reads
    )
    commit = SpyCommit(log)
    return (
        ReplaceAllowedPairs(
            repository=repository,  # type: ignore[arg-type]
            pairs=catalog or FakeCatalog(events=log),
            commit=commit,  # type: ignore[arg-type]
        ),
        repository,
        commit,
    )


async def test_replace_pairs_normalizes_via_market_key() -> None:
    """PUT ``solusdt.p`` (TradingView's own spelling) is stored -- and
    returned -- as ``SOLUSDT``: normalizing is this use case's job, not the
    caller's."""
    use_case, repository, _ = _build()

    updated = await use_case.replace(
        ReplaceAllowedPairsCommand(strategy_id=STRATEGY_ID, pairs=["solusdt.p"])
    )

    assert updated.allowed_pairs.sorted() == ["SOLUSDT"]
    assert repository.updated[0].allowed_pairs.sorted() == ["SOLUSDT"]


async def test_replace_pairs_collapses_duplicates_after_normalization() -> None:
    use_case, _, _ = _build()

    updated = await use_case.replace(
        ReplaceAllowedPairsCommand(
            strategy_id=STRATEGY_ID, pairs=["SOLUSDT.P", "SOLUSDT_PERP", "solusdt"]
        )
    )

    assert updated.allowed_pairs.sorted() == ["SOLUSDT"]


async def test_replace_pairs_with_empty_list_refused() -> None:
    use_case, repository, commit = _build()

    with pytest.raises(EmptyAllowedPairs):
        await use_case.replace(ReplaceAllowedPairsCommand(strategy_id=STRATEGY_ID, pairs=[]))

    assert repository.updated == []
    assert commit.commits == 0


async def test_replace_pairs_where_every_entry_normalizes_to_empty_is_refused() -> None:
    """``.P`` alone strips to nothing -- refused the same way an empty list
    is, not silently stored as a pair no signal can ever match."""
    use_case, repository, commit = _build()

    with pytest.raises(EmptyAllowedPairs):
        await use_case.replace(ReplaceAllowedPairsCommand(strategy_id=STRATEGY_ID, pairs=[".P"]))

    assert repository.updated == []
    assert commit.commits == 0


async def test_replace_pairs_on_an_unknown_strategy_is_refused() -> None:
    repository = FakeRepository(None)
    commit = SpyCommit()
    use_case = ReplaceAllowedPairs(
        repository=repository,  # type: ignore[arg-type]
        pairs=FakeCatalog(),
        commit=commit,  # type: ignore[arg-type]
    )

    with pytest.raises(UnknownStrategy):
        await use_case.replace(
            ReplaceAllowedPairsCommand(strategy_id=uuid4(), pairs=["ETHUSDT"])
        )

    assert repository.updated == []
    assert commit.commits == 0


# --------------------------------------------------------------------------
# 9vc.4 -- only ADDED pairs are validated, and the venue is asked BEFORE the
# row lock (decisions 15 and 41)
#
# Spelling: the venue lists ``STXUSDT``; a replace request sends
# ``STXUSDT_PERP``; the stored form is ``STXUSDT``.
# --------------------------------------------------------------------------

_LOGGER = "strategy_manager.strategies.application.replace_allowed_pairs"
POOL: PoolKey = ("pionex", "spot", "USDT")


def _command(*pairs: str) -> ReplaceAllowedPairsCommand:
    return ReplaceAllowedPairsCommand(strategy_id=STRATEGY_ID, pairs=list(pairs))


def _stored(*pairs: str) -> Strategy:
    return _strategy(allowed_pairs=AllowedPairs(frozenset(pairs)))


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == _LOGGER and record.levelno == logging.WARNING
    ]


async def test_adding_an_unlisted_symbol_refuses_and_leaves_the_stored_list() -> None:
    catalog = FakeCatalog(frozenset({"ETHUSDT", "STXUSDT"}))
    use_case, repository, commit = _build(catalog=catalog)

    with pytest.raises(UnknownPairs) as refused:
        await use_case.replace(_command("ETHUSDT", "YPF"))

    assert refused.value.unknown == ("YPF",)
    assert repository.updated == []
    assert commit.commits == 0
    assert repository.existing is not None
    assert repository.existing.allowed_pairs.sorted() == ["ETHUSDT"]
    assert catalog.asked == [POOL]


async def test_adding_a_listed_symbol_in_another_spelling_is_accepted() -> None:
    catalog = FakeCatalog(frozenset({"STXUSDT"}))
    use_case, repository, _ = _build(catalog=catalog)

    updated = await use_case.replace(_command("STXUSDT_PERP"))

    assert updated.allowed_pairs.sorted() == ["STXUSDT"]
    assert repository.updated[0].allowed_pairs.sorted() == ["STXUSDT"]


async def test_a_stored_delisted_pair_can_be_kept_while_another_pair_is_added() -> None:
    """Decision 15: a pair already stored is never looked up, so one the venue
    has since delisted may stay. Only ``SOLUSDT`` is an addition."""
    catalog = FakeCatalog(frozenset({"SOLUSDT"}))  # ETHUSDT, stored, is NOT listed
    use_case, _, _ = _build(existing=_stored("ETHUSDT"), catalog=catalog)

    updated = await use_case.replace(_command("ETHUSDT", "SOLUSDT.P"))

    assert updated.allowed_pairs.sorted() == ["ETHUSDT", "SOLUSDT"]


async def test_a_stored_delisted_pair_can_be_removed() -> None:
    catalog = FakeCatalog(frozenset({"SOLUSDT"}))
    use_case, _, _ = _build(existing=_stored("ETHUSDT", "SFPUSDT"), catalog=catalog)

    updated = await use_case.replace(_command("ETHUSDT"))

    assert updated.allowed_pairs.sorted() == ["ETHUSDT"]


async def test_a_replacement_that_adds_nothing_never_asks_the_catalogue() -> None:
    """Removing a pair works while the venue is down."""
    catalog = FakeCatalog(failure=PairCatalogUnavailable("venue down"))
    use_case, _, commit = _build(existing=_stored("ETHUSDT", "SOLUSDT"), catalog=catalog)

    updated = await use_case.replace(_command("solusdt.p"))

    assert updated.allowed_pairs.sorted() == ["SOLUSDT"]
    assert commit.commits == 1
    assert catalog.asked == []


async def test_a_removed_delisted_pair_cannot_be_added_back() -> None:
    catalog = FakeCatalog(frozenset({"SOLUSDT"}))
    use_case, repository, _ = _build(existing=_stored("ETHUSDT", "SFPUSDT"), catalog=catalog)
    await use_case.replace(_command("ETHUSDT"))  # SFPUSDT, delisted, is removed

    with pytest.raises(UnknownPairs) as refused:
        await use_case.replace(_command("ETHUSDT", "SFPUSDT"))  # ...and is now an addition

    assert refused.value.unknown == ("SFPUSDT",)
    assert repository.existing is not None
    assert repository.existing.allowed_pairs.sorted() == ["ETHUSDT"]


async def test_an_unreadable_catalogue_refuses_when_a_pair_is_added() -> None:
    catalog = FakeCatalog(failure=PairCatalogUnavailable("venue down"))
    use_case, repository, commit = _build(catalog=catalog)

    with pytest.raises(PairCatalogUnavailable):
        await use_case.replace(_command("SOLUSDT"))

    assert repository.updated == []
    assert commit.commits == 0


async def test_unknown_strategy_and_archived_are_refused_before_the_catalogue_is_asked() -> None:
    unknown_catalog = FakeCatalog()
    use_case = ReplaceAllowedPairs(
        repository=FakeRepository(None),  # type: ignore[arg-type]
        pairs=unknown_catalog,
        commit=SpyCommit(),  # type: ignore[arg-type]
    )
    with pytest.raises(UnknownStrategy):
        await use_case.replace(_command("SOLUSDT"))

    archived_catalog = FakeCatalog()
    archived = _strategy(archived_at=datetime(2026, 9, 1, tzinfo=UTC))
    use_case, _, _ = _build(existing=archived, catalog=archived_catalog)
    with pytest.raises(StrategyArchived):
        await use_case.replace(_command("SOLUSDT"))

    assert unknown_catalog.asked == []
    assert archived_catalog.asked == []


async def test_an_empty_list_is_refused_before_the_catalogue_is_asked() -> None:
    catalog = FakeCatalog()
    use_case, _, _ = _build(catalog=catalog)

    with pytest.raises(EmptyAllowedPairs):
        await use_case.replace(_command(".P"))

    assert catalog.asked == []


async def test_the_catalogue_is_asked_before_the_row_lock_is_taken() -> None:
    """No venue call may run while the strategy's row lock is held: a venue
    timeout is ten seconds, and the same lock serializes the ``enabled`` toggle."""
    events: list[str] = []
    catalog = FakeCatalog(events=events)
    use_case, _, _ = _build(catalog=catalog, events=events)

    await use_case.replace(_command("SOLUSDT"))

    assert events == ["get_by_id", "catalogue", "get_by_id_for_update", "update", "commit"]


async def test_a_strategy_archived_between_the_unlocked_read_and_the_lock_is_still_refused() -> (
    None
):
    def archive(repository: FakeRepository) -> None:
        assert repository.existing is not None
        repository.existing = replace(
            repository.existing, archived_at=datetime(2026, 9, 1, tzinfo=UTC)
        )

    catalog = FakeCatalog()
    use_case, repository, commit = _build(catalog=catalog, between_reads=archive)

    with pytest.raises(StrategyArchived):
        await use_case.replace(_command("SOLUSDT"))

    assert catalog.asked == [POOL]  # the unlocked read passed; the locked one refused
    assert repository.updated == []
    assert commit.commits == 0


async def test_a_stored_list_that_changed_so_an_unvalidated_pair_becomes_an_addition_is_refused_and_nothing_is_written() -> (  # noqa: E501
    None
):
    """Stored ``{ETHUSDT, SOLUSDT}``; the request keeps both and adds ``STXUSDT``,
    so only ``STXUSDT`` is validated. Before the lock is taken another request
    removes ``SOLUSDT``: re-adding it would store a pair nobody checked."""

    def another_request_removes_solusdt(repository: FakeRepository) -> None:
        repository.existing = _stored("ETHUSDT")

    catalog = FakeCatalog(frozenset({"STXUSDT"}))
    use_case, repository, commit = _build(
        existing=_stored("ETHUSDT", "SOLUSDT"),
        catalog=catalog,
        between_reads=another_request_removes_solusdt,
    )

    with pytest.raises(PairsChangedConcurrently):
        await use_case.replace(_command("ETHUSDT", "SOLUSDT", "STXUSDT"))

    assert repository.updated == []
    assert commit.commits == 0
    assert repository.existing is not None
    assert repository.existing.allowed_pairs.sorted() == ["ETHUSDT"]


async def test_a_candidate_that_is_no_longer_an_addition_is_harmless() -> None:
    """The opposite drift: ``STXUSDT`` was validated as a candidate and another
    request has stored it in the meantime. It was checked anyway."""

    def another_request_adds_stxusdt(repository: FakeRepository) -> None:
        repository.existing = _stored("ETHUSDT", "STXUSDT")

    catalog = FakeCatalog(frozenset({"STXUSDT"}))
    use_case, _, commit = _build(
        existing=_stored("ETHUSDT"), catalog=catalog, between_reads=another_request_adds_stxusdt
    )

    updated = await use_case.replace(_command("ETHUSDT", "STXUSDT"))

    assert updated.allowed_pairs.sorted() == ["ETHUSDT", "STXUSDT"]
    assert commit.commits == 1


def _another_request_removes_solusdt(repository: FakeRepository) -> None:
    repository.existing = _stored("ETHUSDT")


@pytest.mark.parametrize(
    ("catalog", "existing", "between", "request_pairs", "must_name"),
    [
        (FakeCatalog(frozenset({"STXUSDT"})), None, None, ["YPF"], "YPF"),
        (FakeCatalog(failure=PairCatalogUnavailable("down")), None, None, ["SOLUSDT"], "unavail"),
        (
            FakeCatalog(failure=PairCatalogNotServed("no source")),
            None,
            None,
            ["SOLUSDT"],
            "no pair catalogue",
        ),
        (
            FakeCatalog(frozenset({"STXUSDT"})),
            _stored("ETHUSDT", "SOLUSDT"),
            _another_request_removes_solusdt,
            ["ETHUSDT", "SOLUSDT", "STXUSDT"],
            "changed",
        ),
    ],
    ids=["unknown-pairs", "unavailable", "not-served", "pairs-changed"],
)
async def test_each_refusal_logs_one_warning(
    caplog: pytest.LogCaptureFixture,
    catalog: FakeCatalog,
    existing: Strategy | None,
    between: Callable[[FakeRepository], None] | None,
    request_pairs: list[str],
    must_name: str,
) -> None:
    use_case, _, _ = _build(existing=existing, catalog=catalog, between_reads=between)

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(DomainError):
        await use_case.replace(_command(*request_pairs))

    records = _warnings(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert str(STRATEGY_ID) in message
    assert "pionex/spot/USDT" in message
    assert must_name in message
