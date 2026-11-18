"""``DeleteAccount`` (openspec/changes/account-deletion, S2-S4).

The use case against fakes of every port: what refuses, what is written, and the
order of locks and writes. The adapters and the lock-hold proof on real
PostgreSQL have their own tests.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from strategy_manager.identity.application.delete_account import (
    AccountChanged,
    AccountDeletionRefused,
    DeleteAccount,
    DeletionReport,
)
from strategy_manager.identity.application.ports import (
    AuthoredStrategy,
    HeldStrategy,
    LockedPool,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
USER = UUID("00000000-0000-0000-0000-00000000000a")
OTHER = UUID("00000000-0000-0000-0000-00000000000b")
ALPHA = UUID("00000000-0000-0000-0000-0000000000a1")
BETA = UUID("00000000-0000-0000-0000-0000000000b2")


def pool(pool_id: int, user_id: UUID = USER, exchange: str = "bybit") -> LockedPool:
    return LockedPool(
        pool_id=pool_id, user_id=user_id, exchange=exchange, venue="usdt-m", currency="USDT"
    )


class World:
    """Every port at once, so one ``events`` list shows the order of everything."""

    def __init__(
        self,
        *,
        own_pools: Sequence[LockedPool] = (),
        authored: Sequence[AuthoredStrategy] = (),
        subscriber_pools: dict[UUID, Sequence[LockedPool]] | None = None,
        symbols: Sequence[str] = (),
        strategy_holdings: dict[UUID, tuple[str, ...]] | None = None,
    ) -> None:
        self.own_pools = list(own_pools)
        self.authored_list = list(authored)
        self.subscriber_pool_map = dict(subscriber_pools or {})
        self.held_symbols = list(symbols)
        self.holdings = dict(strategy_holdings or {})
        self.events: list[tuple[object, ...]] = []
        # Changes that land once the first lock is taken, as a concurrent request would.
        self.after_first_lock: list[object] = []

    # PoolLockPort
    async def acquire(self, user_id: UUID, exchange: str, venue: str, currency: str) -> None:
        self.events.append(("pool_lock", user_id, exchange, venue, currency))
        while self.after_first_lock:
            change = self.after_first_lock.pop()
            assert callable(change)
            change()

    # AccountUsersPort
    async def lock_for_mode_change(self, user_id: UUID) -> None:
        self.events.append(("user_lock", user_id))

    async def wipe(self, user_id: UUID, now: datetime) -> None:
        self.events.append(("wipe", user_id, now))

    # AccountPoolsPort
    async def pools(self, user_id: UUID) -> list[LockedPool]:
        assert user_id == USER
        return list(self.own_pools)

    async def disable_all(self, user_id: UUID) -> int:
        self.events.append(("disable_pools", user_id))
        return len(self.own_pools)

    # AuthoredStrategiesPort
    async def authored(self, user_id: UUID) -> list[AuthoredStrategy]:
        assert user_id == USER
        return sorted(self.authored_list, key=lambda s: s.id)

    async def subscriber_pools(self, strategy_id: UUID) -> list[LockedPool]:
        return list(self.subscriber_pool_map.get(strategy_id, ()))

    async def lock(self, strategy_id: UUID) -> None:
        self.events.append(("strategy_lock", strategy_id))

    async def exposure(self, strategy_id: UUID) -> tuple[str, ...] | None:
        return self.holdings.get(strategy_id)

    async def close(self, strategy_id: UUID, now: datetime) -> int:
        self.events.append(("close", strategy_id, now))
        return len(self.subscriber_pool_map.get(strategy_id, ()))

    # OwnSeatsPort
    async def end_live(self, user_id: UUID, now: datetime) -> int:
        self.events.append(("end_seats", user_id, now))
        return 2

    # AccountCredentialsPort
    async def delete_all(self, user_id: UUID) -> int:
        self.events.append(("delete_keys", user_id))
        return 1

    # LiveExposurePort
    async def symbols(self, user_id: UUID) -> list[str]:
        assert user_id == USER
        return list(self.held_symbols)

    # CommitPort
    async def commit(self) -> None:
        self.events.append(("commit",))

    # ClockPort
    def now(self) -> datetime:
        return NOW

    def kinds(self) -> list[object]:
        return [event[0] for event in self.events]

    def writes(self) -> list[tuple[object, ...]]:
        locks = {"pool_lock", "user_lock", "strategy_lock"}
        return [event for event in self.events if event[0] not in locks]


def use_case(world: World) -> DeleteAccount:
    return DeleteAccount(
        users=world,
        pools=world,
        authored=world,
        seats=world,
        credentials=world,
        exposure=world,
        pool_lock=world,
        commit=world,
        clock=world,
    )


async def test_a_user_holding_nothing_is_wiped_closed_and_committed_once() -> None:
    world = World(
        own_pools=[pool(3)],
        authored=[AuthoredStrategy(id=ALPHA, name="BTC 4h")],
        subscriber_pools={ALPHA: [pool(3), pool(7, OTHER)]},
    )

    report = await use_case(world).execute(USER)

    assert report == DeletionReport(
        strategies_closed=1, seats_ended=4, keys_deleted=1, pools_disabled=1
    )
    assert world.writes() == [
        ("close", ALPHA, NOW),
        ("end_seats", USER, NOW),
        ("delete_keys", USER),
        ("disable_pools", USER),
        ("wipe", USER, NOW),
        ("commit",),
    ]


async def test_every_pool_lock_comes_first_lowest_id_first_then_the_user_then_each_strategy() -> (
    None
):
    world = World(
        own_pools=[pool(9), pool(3, exchange="binance")],
        authored=[AuthoredStrategy(id=BETA, name="B"), AuthoredStrategy(id=ALPHA, name="A")],
        subscriber_pools={
            ALPHA: [pool(5, OTHER), pool(3, exchange="binance")],
            BETA: [pool(1, OTHER)],
        },
    )

    await use_case(world).execute(USER)

    locks = [
        event for event in world.events if event[0] in {"pool_lock", "user_lock", "strategy_lock"}
    ]
    # One lock per pool, the user's own and every subscriber's together, ascending pool_id.
    assert locks == [
        ("pool_lock", OTHER, "bybit", "usdt-m", "USDT"),  # pool 1
        ("pool_lock", USER, "binance", "usdt-m", "USDT"),  # pool 3, read twice, locked once
        ("pool_lock", OTHER, "bybit", "usdt-m", "USDT"),  # pool 5
        ("pool_lock", USER, "bybit", "usdt-m", "USDT"),  # pool 9
        ("user_lock", USER),
        ("strategy_lock", ALPHA),
        ("strategy_lock", BETA),
    ]
    # Every lock before the first write.
    first_write = world.kinds().index("close")
    assert all(kind != "pool_lock" for kind in world.kinds()[first_write:])


async def test_the_users_real_exposure_refuses_and_writes_nothing() -> None:
    world = World(own_pools=[pool(3)], symbols=["BTCUSDT", "STXUSDT"])

    with pytest.raises(AccountDeletionRefused) as refused:
        await use_case(world).execute(USER)

    assert refused.value.symbols == ("BTCUSDT", "STXUSDT")
    assert refused.value.strategies == ()
    assert world.writes() == []


async def test_a_position_on_an_authored_strategy_refuses_naming_it() -> None:
    world = World(
        authored=[
            AuthoredStrategy(id=ALPHA, name="BTC 4h"),
            AuthoredStrategy(id=BETA, name="STX 4h"),
        ],
        strategy_holdings={BETA: ("STXUSDT",)},
    )

    with pytest.raises(AccountDeletionRefused) as refused:
        await use_case(world).execute(USER)

    assert refused.value.symbols == ()
    assert refused.value.strategies == (HeldStrategy(id=BETA, name="STX 4h", symbols=("STXUSDT",)),)
    assert world.writes() == []


async def test_every_reason_is_given_at_once() -> None:
    world = World(
        authored=[
            AuthoredStrategy(id=ALPHA, name="BTC 4h"),
            AuthoredStrategy(id=BETA, name="STX 4h"),
        ],
        symbols=["ETHUSDT"],
        # A live reservation with no symbol read yet still holds the strategy.
        strategy_holdings={ALPHA: (), BETA: ("STXUSDT",)},
    )

    with pytest.raises(AccountDeletionRefused) as refused:
        await use_case(world).execute(USER)

    assert refused.value.symbols == ("ETHUSDT",)
    assert [held.id for held in refused.value.strategies] == [ALPHA, BETA]
    assert world.writes() == []


async def test_exposure_is_read_only_after_every_lock() -> None:
    world = World(own_pools=[pool(3)], authored=[AuthoredStrategy(id=ALPHA, name="A")])
    reads: list[list[object]] = []
    original = world.symbols

    async def symbols(user_id: UUID) -> list[str]:
        reads.append(world.kinds())
        return await original(user_id)

    world.symbols = symbols  # type: ignore[method-assign]

    await use_case(world).execute(USER)

    assert reads == [["pool_lock", "user_lock", "strategy_lock"]]


async def test_a_subscriber_who_joins_while_the_locks_are_taken_refuses_and_writes_nothing() -> (
    None
):
    world = World(
        authored=[AuthoredStrategy(id=ALPHA, name="A")], subscriber_pools={ALPHA: [pool(4, OTHER)]}
    )
    world.after_first_lock.append(
        lambda: world.subscriber_pool_map.__setitem__(ALPHA, [pool(4, OTHER), pool(2, OTHER)])
    )

    with pytest.raises(AccountChanged):
        await use_case(world).execute(USER)

    assert world.writes() == []


async def test_a_strategy_authored_while_the_locks_are_taken_refuses_and_writes_nothing() -> None:
    world = World(own_pools=[pool(3)])
    world.after_first_lock.append(
        lambda: world.authored_list.append(AuthoredStrategy(id=ALPHA, name="New"))
    )

    with pytest.raises(AccountChanged):
        await use_case(world).execute(USER)

    assert world.writes() == []


async def test_a_pool_opened_while_the_locks_are_taken_refuses_and_writes_nothing() -> None:
    world = World(own_pools=[pool(3)])
    world.after_first_lock.append(lambda: world.own_pools.append(pool(8, exchange="binance")))

    with pytest.raises(AccountChanged):
        await use_case(world).execute(USER)

    assert world.writes() == []


async def test_a_user_with_no_pool_and_no_strategy_is_still_wiped() -> None:
    world = World()

    report = await use_case(world).execute(USER)

    assert report == DeletionReport(
        strategies_closed=0, seats_ended=2, keys_deleted=1, pools_disabled=0
    )
    assert world.kinds() == [
        "user_lock",
        "end_seats",
        "delete_keys",
        "disable_pools",
        "wipe",
        "commit",
    ]


async def test_the_log_line_names_the_user_id_and_never_an_e_mail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = World(own_pools=[pool(3)], authored=[AuthoredStrategy(id=ALPHA, name="A")])

    with caplog.at_level(
        logging.INFO, logger="strategy_manager.identity.application.delete_account"
    ):
        await use_case(world).execute(USER)

    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert str(USER) in lines[0]
    assert "@" not in lines[0]


async def test_a_refusal_leaves_a_line_naming_the_user_id(caplog: pytest.LogCaptureFixture) -> None:
    world = World(symbols=["BTCUSDT"])

    with (
        caplog.at_level(
            logging.INFO, logger="strategy_manager.identity.application.delete_account"
        ),
        pytest.raises(AccountDeletionRefused),
    ):
        await use_case(world).execute(USER)

    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert str(USER) in lines[0]
    assert "refused" in lines[0]
