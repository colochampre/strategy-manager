"""``SimulatedVenues``: each user's simulated exchanges (multi-user design AD7).

One set per user, because a venue is one account's view of the market: two users
in simulation on one symbol must keep separate nets, exactly as two accounts
would. The book behind a user's fakes is seeded from that user's rehearsal fills
only (``net_positions_by_symbol(..., mode=Mode.SIMULATION)``), so a real position
of theirs never appears in it.

Process-lifetime, and made the first time a user needs one. A fake keeps its
placed orders in memory and place and settle are separate jobs, so both must
reach the same instance. A user who never simulates costs nothing.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from uuid import UUID

from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook

_PoolKey = tuple[str, str, str]

UserPoolLedgerReader = Callable[[UUID, _PoolKey], Awaitable[Sequence[tuple[str, Decimal]]]]
"""``PoolLedgerReader`` for one named user: their rehearsal fills on this pool."""


@dataclass(frozen=True, slots=True)
class _UserVenues:
    book: FakeVenueBook
    exchanges: tuple[FakeExchangeAdapter, ...]


class SimulatedVenues:
    def __init__(
        self,
        *,
        exchanges: Iterable[str],
        build: Callable[[str, FakeVenueBook], FakeExchangeAdapter],
        ledger_reader: UserPoolLedgerReader,
    ) -> None:
        self._exchanges = tuple(exchanges)
        self._build = build
        self._ledger_reader = ledger_reader
        self._by_user: dict[UUID, _UserVenues] = {}

    def book_of(self, user_id: UUID) -> FakeVenueBook:
        return self._of(user_id).book

    def exchanges_of(self, user_id: UUID) -> Sequence[FakeExchangeAdapter]:
        return self._of(user_id).exchanges

    def _of(self, user_id: UUID) -> _UserVenues:
        venues = self._by_user.get(user_id)
        if venues is None:
            book = FakeVenueBook(partial(self._ledger_reader, user_id))
            venues = _UserVenues(
                book=book,
                exchanges=tuple(self._build(exchange, book) for exchange in self._exchanges),
            )
            self._by_user[user_id] = venues
        return venues
