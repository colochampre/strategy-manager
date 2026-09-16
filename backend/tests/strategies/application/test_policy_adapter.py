"""Unit tests for StrategyPolicyAdapter, using a fake StrategyRepositoryPort
(tasks.md 3.9 — implements allocation.application.StrategyPolicyPort)."""

from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.policy_adapter import (
    StrategyPolicyAdapter,
    UnknownStrategyError,
)
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
