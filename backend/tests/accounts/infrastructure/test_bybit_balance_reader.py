"""Sizing a capital pool from Bybit's unified account.

The subtraction and the refusal are the whole file. Over-report availability
and the allocation engine hands out capital that is already committed; let two
pools read one pot and it hands out the same capital twice.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.accounts.infrastructure.bybit_balance_reader import (
    BybitBalanceReader,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.bybit.read_client import UnifiedCoinBalance

FROZEN_NOW = datetime(2026, 8, 26, 18, 0, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return FROZEN_NOW


class FakeClient:
    def __init__(self, balances: Sequence[UnifiedCoinBalance]) -> None:
        self.calls = 0
        self._balances = list(balances)

    async def unified_balances(self) -> list[UnifiedCoinBalance]:
        self.calls += 1
        return self._balances


def _coin(
    coin: str = "USDT",
    wallet: str = "600",
    position_im: str = "0",
    order_im: str = "0",
    locked: str = "0",
) -> UnifiedCoinBalance:
    return UnifiedCoinBalance(
        coin=coin,
        wallet_balance=Decimal(wallet),
        total_position_im=Decimal(position_im),
        total_order_im=Decimal(order_im),
        locked=Decimal(locked),
        equity=Decimal(wallet),
        usd_value=Decimal(wallet),
        is_collateral=True,
    )


def _reader(*balances: UnifiedCoinBalance) -> tuple[BybitBalanceReader, FakeClient]:
    client = FakeClient(balances)
    return BybitBalanceReader(client, FrozenClock()), client  # type: ignore[arg-type]


async def test_availability_is_the_wallet_minus_what_is_committed() -> None:
    """Initial margin behind positions and resting orders is capital that is
    already spoken for. Counting it would let the allocator hand it out
    again."""
    reader, _ = _reader(_coin(wallet="600", position_im="120", order_im="30", locked="10"))

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].available == Decimal("440")


async def test_the_total_is_the_wallet_including_committed_margin() -> None:
    """Margin behind an open position stays in the wallet. Sizing from the
    total means a second strategy asks for the same amount as the first."""
    reader, _ = _reader(_coin(wallet="600", position_im="120", order_im="30", locked="10"))

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].total == Decimal("600")
    assert readings[0].available == Decimal("440")


async def test_the_total_excludes_unrealized_pnl() -> None:
    """``equity`` carries unrealized PnL. Sizing from it would grow the next
    position out of gains that have not been realized."""
    balance = UnifiedCoinBalance(
        coin="USDT",
        wallet_balance=Decimal("1000"),
        total_position_im=Decimal("300"),
        total_order_im=Decimal("0"),
        locked=Decimal("0"),
        equity=Decimal("1150"),
        usd_value=Decimal("1149.9"),
        is_collateral=True,
    )
    reader, _ = _reader(balance)

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].total == Decimal("1000")


async def test_availability_is_never_the_usd_valuation() -> None:
    """usdValue and totalEquity are USD. On a 5 USDT balance the live account
    reported 4.99968, and reading it would silently convert a
    settlement-currency amount into dollars (rule 7)."""
    balance = UnifiedCoinBalance(
        coin="USDT",
        wallet_balance=Decimal("5"),
        total_position_im=Decimal("0"),
        total_order_im=Decimal("0"),
        locked=Decimal("0"),
        equity=Decimal("5"),
        usd_value=Decimal("4.99968"),
        is_collateral=True,
    )
    reader, _ = _reader(balance)

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].available == Decimal("5")


async def test_a_fully_committed_balance_reads_as_zero_not_negative() -> None:
    """A negative available balance is not a debt this system can act on, and
    handing one to the allocation engine is worse than reporting nothing."""
    reader, _ = _reader(_coin(wallet="100", position_im="150"))

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].available == Decimal("0")


async def test_a_currency_the_account_does_not_hold_reads_as_zero() -> None:
    """Bybit omits coins with no balance. A pool with nothing in it is a pool
    the allocator skips, which is a correct outcome rather than a failure."""
    reader, _ = _reader(_coin(coin="USDT"))

    readings = await reader.read([("usdt-m", "USDC")])

    assert readings[0].available == Decimal("0")
    assert readings[0].total == Decimal("0")


async def test_the_account_is_fetched_once_however_many_pools_there_are() -> None:
    """One unified balance backs every product, so the number of configured
    pools must never multiply API calls."""
    reader, client = _reader(_coin(coin="USDT"), _coin(coin="USDC", wallet="10"))

    await reader.read([("usdt-m", "USDT"), ("coin-m", "USDC")])

    assert client.calls == 1


async def test_every_reading_shares_one_observation_time() -> None:
    """They all come from a single response, so a per-pool timestamp would
    imply a precision that is not there."""
    reader, _ = _reader(_coin(coin="USDT"), _coin(coin="USDC", wallet="10"))

    readings = await reader.read([("usdt-m", "USDT"), ("coin-m", "USDC")])

    assert {reading.observed_at for reading in readings} == {FROZEN_NOW}


async def test_two_pools_over_one_currency_are_refused() -> None:
    """THE guard. Bybit does not segregate collateral, so spot/USDT and
    usdt-m/USDT would be two views of one pot -- and the allocation engine
    could reserve the same money twice, with each reservation looking
    perfectly valid on its own."""
    reader, _ = _reader(_coin())

    with pytest.raises(InvariantViolation, match="reserved twice"):
        await reader.read([("spot", "USDT"), ("usdt-m", "USDT")])


async def test_the_refusal_names_both_pools() -> None:
    """The operator's remedy is to disable one of them, and they need to know
    which two collided."""
    reader, _ = _reader(_coin())

    with pytest.raises(InvariantViolation, match="spot/USDT and usdt-m/USDT"):
        await reader.read([("spot", "USDT"), ("usdt-m", "USDT")])


async def test_different_currencies_are_not_refused() -> None:
    """The guard is about one pot being read twice, not about how many pools
    exist. Separate currencies are separate money."""
    reader, _ = _reader(_coin(coin="USDT"), _coin(coin="USDC", wallet="10"))

    readings = await reader.read([("usdt-m", "USDT"), ("usdt-m", "USDC")])

    assert [r.available for r in readings] == [Decimal("600"), Decimal("10")]


async def test_the_refusal_happens_before_the_network_call() -> None:
    """A configuration that cannot be served safely should not spend a request
    finding that out."""
    reader, client = _reader(_coin())

    with pytest.raises(InvariantViolation):
        await reader.read([("spot", "USDT"), ("usdt-m", "USDT")])

    assert client.calls == 0


async def test_every_reading_is_stamped_bybit() -> None:
    """The snapshot row has to say which exchange answered, or two venues
    named usdt-m become one pool again."""
    reader, _ = _reader(_coin())

    readings = await reader.read([("usdt-m", "USDT")])

    assert readings[0].exchange == "bybit"
