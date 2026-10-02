"""``ReplaceAllowedPairs``: replacing a strategy's entire allowed-pairs list
as a unit, normalized through ``market_key()`` (design.md § 6
"Normalization"; spec: strategy-lifecycle; tasks.md 2e.2).
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.application.update_strategy import UnknownStrategy
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs, EmptyAllowedPairs
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
    def __init__(self, existing: Strategy | None) -> None:
        self.existing = existing
        self.updated: list[Strategy] = []

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        if self.existing is not None and self.existing.id == strategy_id:
            return self.existing
        return None

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        return await self.get_by_id(strategy_id)

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:  # pragma: no cover
        return []

    async def update(self, strategy: Strategy) -> None:
        self.updated.append(strategy)
        self.existing = strategy


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeCatalog:
    """A fake ``PairCatalogPort``. It records the pool of every call, and fails
    with ``failure`` when one is given. The default list holds every symbol the
    older tests in this file add, so they run unchanged."""

    def __init__(
        self,
        available: frozenset[str] = frozenset({"ETHUSDT", "SOLUSDT"}),
        failure: Exception | None = None,
    ) -> None:
        self.available = available
        self.failure = failure
        self.asked: list[PoolKey] = []

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
        if self.failure is not None:
            raise self.failure
        return self.available


def _build(
    existing: Strategy | None = None,
    catalog: FakeCatalog | None = None,
) -> tuple[ReplaceAllowedPairs, FakeRepository, SpyCommit]:
    repository = FakeRepository(_strategy() if existing is None else existing)
    commit = SpyCommit()
    return (
        ReplaceAllowedPairs(
            repository=repository,  # type: ignore[arg-type]
            pairs=catalog or FakeCatalog(),
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
