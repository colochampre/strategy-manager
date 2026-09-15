"""``PionexBalanceReader`` — maps Pionex's per-coin wallets onto pools.

The mapping is where a wrong answer becomes a wrong position size, so these
tests pin which wallet each venue reads from and exactly which number is
treated as available capital.
"""

from datetime import UTC, datetime
from decimal import Decimal

from strategy_manager.accounts.infrastructure.pionex_balance_reader import (
    PionexBalanceReader,
)
from strategy_manager.shared.infrastructure.pionex.read_client import CoinBalance

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

SPOT_POOL = ("spot", "USDT")
USDT_M_POOL = ("usdt-m", "USDT")
COIN_M_POOL = ("coin-m", "BTC")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakePionexClient:
    def __init__(
        self,
        spot: list[CoinBalance] | None = None,
        futures: list[CoinBalance] | None = None,
    ) -> None:
        self._spot = spot or []
        self._futures = futures or []
        self.spot_calls = 0
        self.futures_calls = 0

    async def spot_balances(self) -> list[CoinBalance]:
        self.spot_calls += 1
        return self._spot

    async def futures_balances(self) -> list[CoinBalance]:
        self.futures_calls += 1
        return self._futures


def _coin(
    coin: str, free: str, frozen: str = "0", debts: str | None = None
) -> CoinBalance:
    return CoinBalance(
        coin=coin,
        free=Decimal(free),
        frozen=Decimal(frozen),
        debts=None if debts is None else Decimal(debts),
    )


def _reader(client: FakePionexClient) -> PionexBalanceReader:
    return PionexBalanceReader(client, FrozenClock())  # type: ignore[arg-type]


async def test_a_spot_pool_reads_the_spot_wallet() -> None:
    client = FakePionexClient(
        spot=[_coin("USDT", "600.5")], futures=[_coin("USDT", "999")]
    )

    readings = await _reader(client).read([SPOT_POOL])

    assert readings[0].available == Decimal("600.5")


async def test_a_usdt_m_pool_reads_the_futures_wallet() -> None:
    client = FakePionexClient(
        spot=[_coin("USDT", "600.5")], futures=[_coin("USDT", "999")]
    )

    readings = await _reader(client).read([USDT_M_POOL])

    assert readings[0].available == Decimal("999")


async def test_a_coin_m_pool_reads_the_futures_wallet() -> None:
    client = FakePionexClient(futures=[_coin("BTC", "0.25")])

    readings = await _reader(client).read([COIN_M_POOL])

    assert readings[0].available == Decimal("0.25")


async def test_each_wallet_is_fetched_at_most_once_per_sync() -> None:
    """Configured pools must not multiply API calls: three pools drawing on
    two wallets is still two requests."""
    client = FakePionexClient(
        spot=[_coin("USDT", "1")], futures=[_coin("USDT", "2"), _coin("BTC", "3")]
    )

    await _reader(client).read([SPOT_POOL, USDT_M_POOL, COIN_M_POOL])

    assert client.spot_calls == 1
    assert client.futures_calls == 1


async def test_a_wallet_no_pool_needs_is_never_fetched() -> None:
    client = FakePionexClient(spot=[_coin("USDT", "1")])

    await _reader(client).read([SPOT_POOL])

    assert client.futures_calls == 0


async def test_a_coin_pionex_does_not_report_reads_as_zero() -> None:
    """Pionex omits coins with no balance — the live account returned only
    USDT on spot. An absent coin is an empty pool, not a failure."""
    client = FakePionexClient(spot=[_coin("USDT", "1")])

    readings = await _reader(client).read([("spot", "BTC")])

    assert readings[0].available == Decimal(0)


async def test_frozen_capital_is_not_available() -> None:
    """Frozen means committed to a live exchange order. Counting it would let
    the allocator hand out money that is already spoken for."""
    client = FakePionexClient(spot=[_coin("USDT", "100", frozen="400")])

    readings = await _reader(client).read([SPOT_POOL])

    assert readings[0].available == Decimal("100")


async def test_frozen_capital_counts_toward_the_total() -> None:
    """Frozen capital still belongs to the pool, so it is part of the sizing
    base even though it cannot be granted again."""
    client = FakePionexClient(spot=[_coin("USDT", "100", frozen="400")])

    readings = await _reader(client).read([SPOT_POOL])

    assert readings[0].total == Decimal("500")
    assert readings[0].available == Decimal("100")


async def test_debts_are_subtracted_from_the_total_too() -> None:
    client = FakePionexClient(futures=[_coin("USDT", "1000", frozen="200", debts="250")])

    readings = await _reader(client).read([USDT_M_POOL])

    assert readings[0].total == Decimal("950")


async def test_debts_are_subtracted_from_a_futures_balance() -> None:
    client = FakePionexClient(futures=[_coin("USDT", "1000", debts="250")])

    readings = await _reader(client).read([USDT_M_POOL])

    assert readings[0].available == Decimal("750")


async def test_debts_larger_than_the_balance_floor_at_zero() -> None:
    """The non-negative CHECK on the snapshot table would reject a negative,
    and negative available capital has no meaning for the allocator anyway."""
    client = FakePionexClient(futures=[_coin("USDT", "100", debts="250")])

    readings = await _reader(client).read([USDT_M_POOL])

    assert readings[0].available == Decimal(0)


async def test_every_reading_carries_the_clock_instant() -> None:
    """Freshness is judged against observed_at, so it must come from the
    clock and be shared across the batch."""
    client = FakePionexClient(spot=[_coin("USDT", "1")], futures=[_coin("USDT", "2")])

    readings = await _reader(client).read([SPOT_POOL, USDT_M_POOL])

    assert [reading.observed_at for reading in readings] == [NOW, NOW]


async def test_readings_come_back_one_per_requested_pool() -> None:
    client = FakePionexClient(spot=[_coin("USDT", "1")], futures=[_coin("USDT", "2")])

    readings = await _reader(client).read([SPOT_POOL, USDT_M_POOL, COIN_M_POOL])

    assert [(r.venue, r.settlement_currency) for r in readings] == [
        SPOT_POOL,
        USDT_M_POOL,
        COIN_M_POOL,
    ]
