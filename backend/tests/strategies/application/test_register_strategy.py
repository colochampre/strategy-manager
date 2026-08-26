"""Registering a strategy: the id comes from the alert, and it starts off."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.application.register_strategy import (
    PoolNotAvailable,
    RegisterCommand,
    RegisterStrategy,
    StrategyAlreadyRegistered,
)
from strategy_manager.strategies.domain.strategy import FillMode, Strategy

# The real signalType of one of the owner's Pionex signals. Using a realistic
# one makes the point the docstring makes: this id is copied, never generated.
SIGNAL_TYPE = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")


class FakeRepository:
    def __init__(self, existing: Strategy | None = None) -> None:
        self.inserted: list[Strategy] = []
        self._existing = existing

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        if self._existing is not None and self._existing.id == strategy_id:
            return self._existing
        return None

    async def insert(self, strategy: Strategy) -> None:
        self.inserted.append(strategy)

    async def list_all(self) -> list[Strategy]:  # pragma: no cover - unused here
        return self.inserted

    async def update(self, strategy: Strategy) -> None:  # pragma: no cover
        raise NotImplementedError


class FakePools:
    def __init__(self, pools: list[tuple[Venue, Currency]] | None = None) -> None:
        self._pools = pools if pools is not None else [(Venue.SPOT, Currency.USDT)]

    async def enabled_pools(self) -> list[tuple[Venue, Currency]]:
        return self._pools


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _command(**overrides: object) -> RegisterCommand:
    fields: dict[str, object] = {
        "strategy_id": SIGNAL_TYPE,
        "name": "BAT - RSI Divergences v1.3",
        "venue": Venue.SPOT,
        "settlement_currency": Currency.USDT,
        "fill_mode": FillMode.PARTIAL,
        "allocation_percent": Decimal("100"),
    }
    fields.update(overrides)
    return RegisterCommand(**fields)  # type: ignore[arg-type]


def _build(
    existing: Strategy | None = None,
    pools: list[tuple[Venue, Currency]] | None = None,
) -> tuple[RegisterStrategy, FakeRepository, SpyCommit]:
    repository = FakeRepository(existing)
    commit = SpyCommit()
    use_case = RegisterStrategy(
        repository=repository,  # type: ignore[arg-type]
        pools=FakePools(pools),  # type: ignore[arg-type]
        commit=commit,
    )
    return use_case, repository, commit


async def test_the_id_is_the_one_supplied_and_never_generated() -> None:
    """The webhook looks a strategy up under the alert's signalType. An id
    invented here would match no alert that will ever arrive."""
    use_case, repository, _ = _build()

    strategy = await use_case.register(_command())

    assert strategy.id == SIGNAL_TYPE
    assert repository.inserted[0].id == SIGNAL_TYPE


async def test_a_newly_registered_strategy_is_disabled() -> None:
    """Registering answers "is this configured right?"; enabling answers
    "should this trade now?". Only the second one moves money, so they are
    separate acts and this one cannot perform the other."""
    use_case, repository, _ = _build()

    strategy = await use_case.register(_command())

    assert strategy.enabled is False
    assert repository.inserted[0].enabled is False


async def test_the_command_offers_no_way_to_register_an_enabled_strategy() -> None:
    """Structural: the guard above is not an argument that happens to be
    false, it is a field that does not exist."""
    assert "enabled" not in RegisterCommand.__dataclass_fields__


async def test_registering_twice_under_one_id_is_refused() -> None:
    """That id comes from an alert the owner configured elsewhere. Two
    strategies under one id means the alert is misconfigured, and quietly
    overwriting would hide it."""
    existing = await _registered()
    use_case, repository, commit = _build(existing=existing)

    with pytest.raises(StrategyAlreadyRegistered, match="already registered"):
        await use_case.register(_command(name="something else"))

    assert repository.inserted == []
    assert commit.commits == 0


async def test_a_pool_that_is_not_enabled_is_refused_before_the_write() -> None:
    """The composite FK cannot catch this: the row exists, it is just
    disabled. The allocation engine reads only enabled pools, so such a
    strategy would accept every signal and size none of them."""
    use_case, repository, commit = _build(pools=[(Venue.SPOT, Currency.USDT)])

    with pytest.raises(PoolNotAvailable, match="usdt-m/USDT"):
        await use_case.register(_command(venue=Venue.USDT_M))

    assert repository.inserted == []
    assert commit.commits == 0


async def test_the_refusal_names_the_pools_that_are_available() -> None:
    """The operator's remedy is to pick one of them or enable theirs, and
    both need the list."""
    use_case, _, _ = _build(
        pools=[(Venue.SPOT, Currency.USDT), (Venue.COIN_M, Currency.BTC)]
    )

    with pytest.raises(PoolNotAvailable, match="coin-m/BTC, spot/USDT"):
        await use_case.register(_command(venue=Venue.USDT_M))


async def test_an_account_with_no_enabled_pools_says_so_plainly() -> None:
    use_case, _, _ = _build(pools=[])

    with pytest.raises(PoolNotAvailable, match="Enabled pools are none"):
        await use_case.register(_command())


async def test_the_write_is_committed() -> None:
    use_case, _, commit = _build()

    await use_case.register(_command())

    assert commit.commits == 1


async def test_the_allocation_percent_is_carried_onto_the_policy() -> None:
    use_case, repository, _ = _build()

    await use_case.register(_command(allocation_percent=Decimal("25")))

    assert repository.inserted[0].policy.allocation_percent.value == Decimal("25")


async def _registered() -> Strategy:
    use_case, repository, _ = _build()
    await use_case.register(_command(strategy_id=SIGNAL_TYPE))
    return repository.inserted[0]


async def test_a_second_strategy_on_the_same_pool_is_allowed() -> None:
    """Pools are shared by design -- competing for one pool is the entire
    point of the system. Only the ID has to be unique."""
    use_case, repository, _ = _build()

    await use_case.register(_command())
    await use_case.register(_command(strategy_id=uuid4(), name="SOL 4h"))

    assert len(repository.inserted) == 2
