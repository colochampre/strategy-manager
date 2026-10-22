"""Unit tests for PoolBalanceAdapter, mapping a startup-loaded PoolConfig
snapshot plus a FakeBalanceSource to allocation.application.PoolBalancePort
(tasks.md 3.11).

The map is keyed by ``(user_id, market)`` (multi-user design AD8): two users may
each hold a pool on one market, and the pool read is the asking user's own."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.ports import PoolFunds
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.owner import OWNER_ID

OTHER_ID = uuid4()
SPOT = ("pionex", "spot", "USDT")


def _pool(user_id: UUID, minimum: str) -> PoolConfig:
    return PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        user_id=user_id,
        min_order_size=Decimal(minimum),
    )


def _pools() -> dict[tuple[UUID, tuple[str, str, str]], PoolConfig]:
    return {(OWNER_ID, SPOT): _pool(OWNER_ID, "10")}


class _RecordingBalanceSource:
    """Answers per user, and records which user each read was for."""

    def __init__(self, funds: dict[UUID, PoolFunds]) -> None:
        self._funds = funds
        self.users: list[UUID] = []

    async def read_balance(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> PoolFunds:
        self.users.append(user_id)
        return self._funds[user_id]


async def test_read_combines_pool_config_and_live_balance() -> None:
    balance_source = FakeBalanceSource()
    balance_source.set_funds(
        "pionex", "spot", "USDT", total=Decimal("1000"), available=Decimal("700")
    )
    adapter = PoolBalanceAdapter(_pools(), balance_source)

    pool_balance = await adapter.read(OWNER_ID, "pionex", "spot", "USDT")

    assert pool_balance.total == Decimal("1000")
    assert pool_balance.available == Decimal("700")
    assert pool_balance.min_order_size == Decimal("10")


async def test_read_raises_for_unconfigured_pool() -> None:
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation):
        await adapter.read(OWNER_ID, "pionex", "coin-m", "BTC")


async def test_the_same_venue_on_another_exchange_is_not_this_pool() -> None:
    """``(bybit, spot, USDT)`` is not ``(pionex, spot, USDT)``. Resolving it
    to the configured one would size a Bybit strategy from Pionex's wallet."""
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation):
        await adapter.read(OWNER_ID, "bybit", "spot", "USDT")


# --- Two users, one market (multi-user design AD8) ----------------------------


async def test_each_user_reads_their_own_pool_and_their_own_balance() -> None:
    """Both users hold a pool on ``pionex/spot/USDT``, minimum 10 and 25, with
    1000 and 40 in it. Each read answers the asking user's minimum and money,
    and asks the balance source for that user."""
    source = _RecordingBalanceSource(
        {
            OWNER_ID: PoolFunds(total=Decimal("1000"), available=Decimal("700")),
            OTHER_ID: PoolFunds(total=Decimal("40"), available=Decimal("30")),
        }
    )
    adapter = PoolBalanceAdapter(
        {(OWNER_ID, SPOT): _pool(OWNER_ID, "10"), (OTHER_ID, SPOT): _pool(OTHER_ID, "25")},
        source,
    )

    owner = await adapter.read(OWNER_ID, *SPOT)
    other = await adapter.read(OTHER_ID, *SPOT)

    assert (owner.total, owner.available, owner.min_order_size) == (
        Decimal("1000"),
        Decimal("700"),
        Decimal("10"),
    )
    assert (other.total, other.available, other.min_order_size) == (
        Decimal("40"),
        Decimal("30"),
        Decimal("25"),
    )
    assert source.users == [OWNER_ID, OTHER_ID]


async def test_another_users_pool_on_the_same_market_never_answers() -> None:
    """Only the owner holds a pool on the market. The second user's read
    raises, naming that user, instead of sizing from the owner's pool."""
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation, match=f"of user {str(OTHER_ID)[:8]}"):
        await adapter.read(OTHER_ID, *SPOT)
