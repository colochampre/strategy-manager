"""Updating a strategy, and the move it refuses to make.

The refusal is the substance here. Switching a strategy between capital pools
routes the close of an open position to the wrong adapter, which leaves a real
holding open while the system believes it closed.
"""

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

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError

    async def list_all(self) -> list[Strategy]:  # pragma: no cover
        return []

    async def update(self, strategy: Strategy) -> None:
        self.updated.append(strategy)


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build(
    existing: Strategy | None = None,
) -> tuple[UpdateStrategy, FakeRepository, SpyCommit]:
    repository = FakeRepository(_strategy() if existing is None else existing)
    commit = SpyCommit()
    return (
        UpdateStrategy(repository=repository, commit=commit),  # type: ignore[arg-type]
        repository,
        commit,
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
    use_case, repository, commit = _build()

    updated = await use_case.update(UpdateCommand(strategy_id=STRATEGY_ID, enabled=True))

    assert updated.enabled is True
    assert repository.updated[0].enabled is True
    assert commit.commits == 1


async def test_omitted_fields_are_left_exactly_as_they_were() -> None:
    """``None`` means unchanged, so a caller flipping one switch cannot
    silently reset the rest to defaults it never sent."""
    existing = _strategy(name="original", enabled=True)
    use_case, repository, _ = _build(existing)

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
    use_case, _, _ = _build()

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
    use_case, _, _ = _build(_strategy(enabled=True))

    updated = await use_case.update(
        UpdateCommand(strategy_id=STRATEGY_ID, enabled=False)
    )

    assert updated.enabled is False
    assert updated.id == STRATEGY_ID


async def test_an_unregistered_id_is_refused_rather_than_created() -> None:
    use_case, repository, commit = _build()

    with pytest.raises(UnknownStrategy, match="no strategy registered"):
        await use_case.update(UpdateCommand(strategy_id=uuid4(), enabled=True))

    assert repository.updated == []
    assert commit.commits == 0


async def test_an_invalid_percent_is_refused_by_the_domain() -> None:
    """``AllocationPercent`` enforces 0 < value <= 100, and the update path
    goes through it rather than around it."""
    from strategy_manager.shared.domain.errors import InvariantViolation

    use_case, repository, _ = _build()

    with pytest.raises(InvariantViolation):
        await use_case.update(
            UpdateCommand(strategy_id=STRATEGY_ID, allocation_percent=Decimal("150"))
        )

    assert repository.updated == []
