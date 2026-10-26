"""``DeleteCredential`` over fakes: the ORDER of its steps, what it refuses before
touching anything, and what it logs (tasks.md 6e.10; owner decisions 22 and 31).

The fakes share one event log, so "the advisory lock came first" is an assertion
on a list. What a real lock and a real transaction do is proven separately, on
real PostgreSQL, in ``test_delete_credential_integration.py``.
"""

from uuid import UUID, uuid4

import pytest

from strategy_manager.accounts.application.delete_credential import (
    DeleteCredential,
    ExchangeNotFlat,
    ExchangeNotServed,
    NoActiveCredential,
)
from strategy_manager.accounts.application.ports import (
    ActiveCredential,
    EnabledStrategy,
    PoolExposure,
    PoolKey,
)
from tests.owner import OWNER_ID

EMPTY =PoolExposure(
    enabled_strategies=(),
    symbols=frozenset(),
    allocations=(),
    live_reservations=(),
    in_flight_attempts=(),
    open_discrepancies=frozenset(),
)
SENTINEL_LABEL = "default"
ACTIVE = ActiveCredential("bybit", SENTINEL_LABEL, "abcd")


class Events:
    def __init__(self) -> None:
        self.log: list[str] = []


class FakeLock:
    def __init__(self, events: Events) -> None:
        self._events = events
        self.pools: list[tuple[str, str, str]] = []
        self.users: list[UUID] = []

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self.users.append(user_id)
        self.pools.append((exchange, venue, settlement_currency))
        self._events.log.append("lock")


class FakeRevoker:
    def __init__(self, events: Events, active: ActiveCredential | None) -> None:
        self._events = events
        self._active = active
        self.deactivated: list[str] = []
        self.users: list[UUID] = []

    async def lock_active(self, user_id: UUID, exchange: str) -> ActiveCredential | None:
        self._events.log.append("lock_active")
        self.users.append(user_id)
        return self._active

    async def deactivate(self, user_id: UUID, exchange: str) -> None:
        self._events.log.append("deactivate")
        self.users.append(user_id)
        self.deactivated.append(exchange)


class FakeExposure:
    def __init__(self, events: Events, exposure: PoolExposure = EMPTY) -> None:
        self._events = events
        self._exposure = exposure
        self.pools: list[PoolKey] = []
        self.users: list[UUID] = []

    async def exposure(self, user_id: UUID, pool: PoolKey) -> PoolExposure:
        self._events.log.append("exposure")
        self.users.append(user_id)
        self.pools.append(pool)
        return self._exposure


class FakePools:
    def __init__(self, events: Events, flipped: bool = True) -> None:
        self._events = events
        self._flipped = flipped
        self.disabled: list[str] = []
        self.users: list[UUID] = []

    async def enable(self, user_id: UUID, exchange: str) -> bool:
        raise AssertionError("deleting a key never enables a pool")

    async def disable(self, user_id: UUID, exchange: str) -> bool:
        self._events.log.append("disable")
        self.users.append(user_id)
        self.disabled.append(exchange)
        return self._flipped


class FakeCommit:
    def __init__(self, events: Events) -> None:
        self._events = events
        self.commits = 0

    async def commit(self) -> None:
        self._events.log.append("commit")
        self.commits += 1


class Built:
    def __init__(
        self,
        *,
        active: ActiveCredential | None = ACTIVE,
        exposure: PoolExposure = EMPTY,
        flipped: bool = True,
    ) -> None:
        self.events = Events()
        self.lock = FakeLock(self.events)
        self.revoker = FakeRevoker(self.events, active)
        self.exposure = FakeExposure(self.events, exposure)
        self.pools = FakePools(self.events, flipped)
        self.commit = FakeCommit(self.events)
        self.use_case = DeleteCredential(
            self.revoker, self.lock, self.exposure, self.pools, self.commit
        )


async def test_the_steps_run_lock_then_row_then_exposure_then_writes_then_commit() -> None:
    """Lock order (CLAUDE.md, Review): the pool advisory lock FIRST, then the row
    lock. The task text listed them the other way round; that order is the
    deadlock ``ArchiveStrategy`` already documents."""
    built = Built()

    await built.use_case.execute(OWNER_ID, "bybit")

    assert built.events.log == [
        "lock",
        "lock_active",
        "exposure",
        "deactivate",
        "disable",
        "commit",
    ]


async def test_the_lock_is_the_exchanges_known_pool_never_a_caller_supplied_one() -> None:
    built = Built()

    await built.use_case.execute(OWNER_ID, "bybit")

    assert built.lock.pools == [("bybit", "usdt-m", "USDT")]
    assert built.exposure.pools == [("bybit", "usdt-m", "USDT")]
    assert built.pools.disabled == ["bybit"]


async def test_the_pool_disabled_is_the_deleting_users_never_another_users() -> None:
    """Two users may each hold a pool on this market (AD8): the one switched
    off is the signed-in user's, whoever else holds one."""
    other = UUID("00000000-0000-4000-8000-0000000000b2")
    built = Built()

    await built.use_case.execute(other, "bybit")

    assert built.pools.users == [other]


async def test_the_key_locked_and_deactivated_is_the_deleting_users() -> None:
    """AD8: the row locked and then deactivated is the signed-in user's key,
    never another user's on the same exchange."""
    other = UUID("00000000-0000-4000-8000-0000000000b2")
    built = Built()

    await built.use_case.execute(other, "bybit")

    assert built.revoker.users == [other, other]


async def test_the_pool_lock_taken_is_the_deleting_users() -> None:
    """B.4: the advisory lock identifies ONE user's pool, so the delete takes the
    signed-in user's, never a lock another user's allocations wait on."""
    other = UUID("00000000-0000-4000-8000-0000000000b2")
    built = Built()

    await built.use_case.execute(other, "bybit")

    assert built.lock.users == [other]


async def test_the_exposure_read_is_the_deleting_users() -> None:
    """AD8: the live reservations that stand in the way of deleting a key are
    the signed-in user's, never another user's on the same market."""
    other = UUID("00000000-0000-4000-8000-0000000000b2")
    built = Built()

    await built.use_case.execute(other, "bybit")

    assert built.exposure.users == [other]


@pytest.mark.parametrize("exchange", ["pionex", "kraken", ""])
async def test_an_exchange_without_a_known_pool_is_refused_before_any_lock_or_read(
    exchange: str,
) -> None:
    """Owner decision 31: no advisory lock, no row read, no exposure query and no
    write ever runs for an exchange outside ``KNOWN_FUTURES_POOLS``."""
    built = Built(active=ActiveCredential(exchange, SENTINEL_LABEL, "abcd"))

    with pytest.raises(ExchangeNotServed):
        await built.use_case.execute(OWNER_ID, exchange)

    assert built.events.log == []
    assert built.revoker.deactivated == []
    assert built.pools.disabled == []


async def test_no_active_credential_raises_after_the_lock_and_writes_nothing() -> None:
    built = Built(active=None)

    with pytest.raises(NoActiveCredential):
        await built.use_case.execute(OWNER_ID, "bybit")

    assert built.events.log == ["lock", "lock_active"]
    assert built.commit.commits == 0


@pytest.mark.parametrize(
    "exposure",
    [
        PoolExposure((EnabledStrategy(uuid4(), "alpha"),), frozenset(), (), (), (), frozenset()),
        PoolExposure((), frozenset({"ETHUSDT"}), (), (), (), frozenset()),
        PoolExposure((), frozenset(), (uuid4(),), (), (), frozenset()),
        PoolExposure((), frozenset(), (), (uuid4(),), (), frozenset()),
        PoolExposure((), frozenset(), (), (), (uuid4(),), frozenset()),
        PoolExposure((), frozenset(), (), (), (), frozenset({"STXUSDT"})),
    ],
    ids=[
        "enabled_strategy",
        "symbol",
        "allocation",
        "live_reservation",
        "in_flight_attempt",
        "open_discrepancy",
    ],
)
async def test_any_one_kind_of_exposure_refuses_and_nothing_is_written(
    exposure: PoolExposure,
) -> None:
    built = Built(exposure=exposure)

    with pytest.raises(ExchangeNotFlat) as caught:
        await built.use_case.execute(OWNER_ID, "bybit")

    assert caught.value.exposure == exposure
    assert built.events.log == ["lock", "lock_active", "exposure"]
    assert built.commit.commits == 0


async def test_a_success_logs_one_info_naming_the_exchange_last4_and_disabled_pool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    built = Built()

    with caplog.at_level("DEBUG"):
        await built.use_case.execute(OWNER_ID, "bybit")

    records = [r for r in caplog.records if r.name.startswith("strategy_manager")]
    assert [r.levelname for r in records] == ["INFO"]
    message = records[0].getMessage()
    assert "bybit" in message
    assert "abcd" in message
    assert "usdt-m/USDT" in message
    assert "disabled" in message


async def test_a_success_on_an_already_disabled_pool_says_so_instead_of_claiming_a_flip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    built = Built(flipped=False)

    with caplog.at_level("DEBUG"):
        result = await built.use_case.execute(OWNER_ID, "bybit")

    assert result.pool_disabled is False
    (record,) = [r for r in caplog.records if r.name.startswith("strategy_manager")]
    assert "already disabled" in record.getMessage()


async def test_a_refusal_logs_one_warning_naming_the_exchange_and_what_blocks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id: UUID = uuid4()
    reservation: UUID = uuid4()
    exposure = PoolExposure(
        (EnabledStrategy(strategy_id, "alpha"),),
        frozenset({"ETHUSDT"}),
        (),
        (reservation,),
        (),
        frozenset(),
    )
    built = Built(exposure=exposure)

    with caplog.at_level("DEBUG"), pytest.raises(ExchangeNotFlat):
        await built.use_case.execute(OWNER_ID, "bybit")

    records = [r for r in caplog.records if r.name.startswith("strategy_manager")]
    assert [r.levelname for r in records] == ["WARNING"]
    message = records[0].getMessage()
    assert "bybit" in message
    assert "alpha" in message
    assert "ETHUSDT" in message
    assert str(reservation) in message
    assert "abcd" not in message


async def test_a_refusal_for_an_open_discrepancy_names_its_symbol_in_the_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Owner decision 70: the symbol the venue holds and the ledger does not."""
    built = Built(exposure=PoolExposure((), frozenset(), (), (), (), frozenset({"STXUSDT"})))

    with caplog.at_level("DEBUG"), pytest.raises(ExchangeNotFlat) as caught:
        await built.use_case.execute(OWNER_ID, "bybit")

    assert "STXUSDT" in str(caught.value)
    (record,) = [r for r in caplog.records if r.name.startswith("strategy_manager")]
    assert "open_discrepancies=['STXUSDT']" in record.getMessage()
    assert built.revoker.deactivated == []


async def test_the_refusal_carries_no_key_fragment_anywhere() -> None:
    blocking = PoolExposure(
        (EnabledStrategy(uuid4(), "alpha"),), frozenset(), (), (), (), frozenset()
    )
    built = Built(exposure=blocking)

    with pytest.raises(ExchangeNotFlat) as caught:
        await built.use_case.execute(OWNER_ID, "bybit")

    assert "abcd" not in str(caught.value)
