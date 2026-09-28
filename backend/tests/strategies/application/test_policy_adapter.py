"""Unit tests for StrategyPolicyAdapter, using a fake StrategyRepositoryPort
(tasks.md 3.9 — implements allocation.application.StrategyPolicyPort).

Unit 2b extends this mapping with ``StrategyPolicySnapshot.name``,
``.archived`` and ``.allowed_pairs``, threaded from ``Strategy.name``,
``.archived_at`` and ``.allowed_pairs`` (design.md § "File changes",
``strategies/application/policy_adapter.py``)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.policy_adapter import (
    StrategyPolicyAdapter,
    UnknownStrategyError,
)
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy


class _FakeStrategyRepository:
    def __init__(self, strategies: dict[UUID, Strategy]) -> None:
        self._strategies = strategies

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        return self._strategies.get(strategy_id)

    async def insert(self, strategy: Strategy) -> None:
        self._strategies[strategy.id] = strategy


async def test_policy_for_maps_strategy_to_snapshot_dto() -> None:
    strategy_id = uuid4()
    strategy = Strategy(
        id=strategy_id,
        name="eth-trend",
        policy=AllocationPolicy(exchange=Exchange.PIONEX, 
            venue=Venue.COIN_M, settlement_currency=Currency.ETH, fill_mode=FillMode.PARTIAL
        ),
        enabled=True,
    )
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({strategy_id: strategy}))

    snapshot = await adapter.policy_for(strategy_id)

    assert snapshot.strategy_id == strategy_id
    assert snapshot.enabled is True
    assert snapshot.fill_mode == "PARTIAL"
    assert snapshot.venue == "coin-m"
    assert snapshot.settlement_currency == "ETH"


async def test_policy_for_maps_a_disabled_skip_strategy() -> None:
    strategy_id = uuid4()
    strategy = Strategy(
        id=strategy_id,
        name="btc-grid",
        policy=AllocationPolicy(exchange=Exchange.PIONEX, 
            venue=Venue.SPOT, settlement_currency=Currency.USDT, fill_mode=FillMode.SKIP
        ),
        enabled=False,
    )
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({strategy_id: strategy}))

    snapshot = await adapter.policy_for(strategy_id)

    assert snapshot.enabled is False
    assert snapshot.fill_mode == "SKIP"
    assert snapshot.venue == "spot"


async def test_policy_for_raises_for_unknown_strategy() -> None:
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({}))

    with pytest.raises(UnknownStrategyError):
        await adapter.policy_for(uuid4())


async def test_policy_for_maps_name_and_a_non_archived_strategy_with_allowed_pairs() -> None:
    """unit 2b: an active strategy's snapshot carries its name, ``archived
    is False`` and its allowed pairs, unchanged from the domain VO."""
    strategy_id = uuid4()
    strategy = Strategy(
        id=strategy_id,
        name="eth-trend",
        policy=AllocationPolicy(
            exchange=Exchange.PIONEX,
            venue=Venue.COIN_M,
            settlement_currency=Currency.ETH,
            fill_mode=FillMode.PARTIAL,
        ),
        enabled=True,
        allowed_pairs=AllowedPairs(frozenset({"ETHUSDT", "BTCUSDT"})),
    )
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({strategy_id: strategy}))

    snapshot = await adapter.policy_for(strategy_id)

    assert snapshot.name == "eth-trend"
    assert snapshot.archived is False
    assert snapshot.allowed_pairs == frozenset({"ETHUSDT", "BTCUSDT"})


async def test_policy_for_maps_archived_true_once_archived_at_is_set() -> None:
    """unit 2b: ``archived`` is a presence test on ``archived_at`` -- every
    consumer (``process_signal.py``, ``AllocateCapital``'s in-lock re-check)
    only ever needs "is it archived", never when."""
    strategy_id = uuid4()
    strategy = Strategy(
        id=strategy_id,
        name="btc-grid",
        policy=AllocationPolicy(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            fill_mode=FillMode.SKIP,
        ),
        enabled=False,
        archived_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({strategy_id: strategy}))

    snapshot = await adapter.policy_for(strategy_id)

    assert snapshot.archived is True


async def test_policy_for_maps_an_empty_allowed_pairs_list() -> None:
    """decision 13: a seeded strategy with no prior signals is legitimately
    empty. The mapping must carry that through as an empty ``frozenset``,
    not silently substitute a placeholder."""
    strategy_id = uuid4()
    strategy = Strategy(
        id=strategy_id,
        name="new-strategy",
        policy=AllocationPolicy(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            fill_mode=FillMode.PARTIAL,
        ),
        enabled=True,
    )
    adapter = StrategyPolicyAdapter(_FakeStrategyRepository({strategy_id: strategy}))

    snapshot = await adapter.policy_for(strategy_id)

    assert snapshot.allowed_pairs == frozenset()
