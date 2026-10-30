"""``SimulatedVenues``: each user's simulated exchanges (multi-user design AD7,
tasks.md E.3).

Two users in simulation on one symbol keep separate nets, and a user's fakes
last as long as the process: a fake holds its placed orders in memory, so place
and settle, which are separate jobs, must reach the same instance.
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.execution.infrastructure.simulated_venues import SimulatedVenues

POOL = ("bybit", "usdt-m", "USDT")


class FakeLedger:
    def __init__(self, by_user: dict[UUID, list[tuple[str, Decimal]]] | None = None) -> None:
        self._by_user = by_user or {}
        self.asked: list[tuple[UUID, tuple[str, str, str]]] = []

    async def __call__(
        self, user_id: UUID, pool: tuple[str, str, str]
    ) -> Sequence[tuple[str, Decimal]]:
        self.asked.append((user_id, pool))
        return self._by_user.get(user_id, [])


def _build(exchange: str, book: FakeVenueBook) -> FakeExchangeAdapter:
    return FakeExchangeAdapter(exchange=exchange, book=book, fee_rate=Decimal("0.00055"))


def _venues(ledger: FakeLedger | None = None) -> SimulatedVenues:
    return SimulatedVenues(
        exchanges=("binance", "bybit"), build=_build, ledger_reader=ledger or FakeLedger()
    )


async def test_two_users_on_one_symbol_keep_separate_nets() -> None:
    venues = _venues()
    first, second = uuid4(), uuid4()

    venues.book_of(first).record_fill("bybit", "SOLUSDT.P", Decimal("2"))
    venues.book_of(second).record_fill("bybit", "SOLUSDT", Decimal("-5"))

    assert await venues.book_of(first).open_positions(POOL) == [("SOLUSDT", Decimal("2"))]
    assert await venues.book_of(second).open_positions(POOL) == [("SOLUSDT", Decimal("-5"))]


async def test_each_users_book_is_seeded_from_that_users_ledger_only() -> None:
    first, second = uuid4(), uuid4()
    ledger = FakeLedger(
        {first: [("SOLUSDT", Decimal("2"))], second: [("SOLUSDT", Decimal("5"))]}
    )
    venues = _venues(ledger)

    assert await venues.book_of(first).open_positions(POOL) == [("SOLUSDT", Decimal("2"))]
    assert await venues.book_of(second).open_positions(POOL) == [("SOLUSDT", Decimal("5"))]
    assert ledger.asked == [(first, POOL), (second, POOL)]


def test_a_users_fakes_outlive_the_job_that_asked_for_them() -> None:
    venues = _venues()
    user = uuid4()

    assert list(venues.exchanges_of(user)) == list(venues.exchanges_of(user))


def test_a_user_holds_one_fake_per_exchange_all_on_their_own_book() -> None:
    venues = _venues()
    user = uuid4()

    fakes = venues.exchanges_of(user)

    assert [fake.exchange for fake in fakes] == ["binance", "bybit"]
    assert all(fake.book is venues.book_of(user) for fake in fakes)


def test_two_users_never_share_a_fake() -> None:
    venues = _venues()

    first = venues.exchanges_of(uuid4())
    second = venues.exchanges_of(uuid4())

    assert not {id(fake) for fake in first} & {id(fake) for fake in second}
