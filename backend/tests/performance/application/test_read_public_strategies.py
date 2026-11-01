"""``ReadPublicStrategies`` over a fake source (tasks.md F.4, decisions 15, 28 and 30)."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.application.ports import PublicListing
from strategy_manager.performance.application.read_public_strategies import ReadPublicStrategies
from strategy_manager.performance.domain.public_capital import LiveSeat
from strategy_manager.performance.domain.public_record import RecordSignal

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _listing(strategy_id: UUID | None = None) -> PublicListing:
    return PublicListing(
        strategy_id=strategy_id or uuid4(),
        name="Trend",
        author_name="Ana",
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        created_at=T0,
    )


def _round_trip(entry: str, exit_price: str) -> tuple[RecordSignal, RecordSignal]:
    return (
        RecordSignal("STXUSDT.P", T0, Decimal("1"), Decimal(entry)),
        RecordSignal("STXUSDT.P", T0 + timedelta(hours=1), Decimal("0"), Decimal(exit_price)),
    )


class _Source:
    def __init__(
        self,
        listings: Sequence[PublicListing] = (),
        signals: Mapping[UUID, Sequence[RecordSignal]] | None = None,
        seats: Mapping[UUID, Sequence[LiveSeat]] | None = None,
    ) -> None:
        self._listings = listings
        self._signals = signals or {}
        self._seats = seats or {}
        self.calls: list[tuple[str, tuple[UUID, ...]]] = []

    async def listings(self) -> Sequence[PublicListing]:
        self.calls.append(("listings", ()))
        return self._listings

    async def listing(self, strategy_id: UUID) -> PublicListing | None:
        self.calls.append(("listing", (strategy_id,)))
        found = [each for each in self._listings if each.strategy_id == strategy_id]
        return found[0] if found else None

    async def signals(self, strategy_ids: Sequence[UUID]) -> Mapping[UUID, Sequence[RecordSignal]]:
        self.calls.append(("signals", tuple(strategy_ids)))
        return self._signals

    async def live_seats(self, strategy_ids: Sequence[UUID]) -> Mapping[UUID, Sequence[LiveSeat]]:
        self.calls.append(("live_seats", tuple(strategy_ids)))
        return self._seats


async def test_a_strategy_carries_its_listing_record_live_count_and_capital() -> None:
    listing = _listing()
    source = _Source(
        [listing],
        {listing.strategy_id: _round_trip("100", "110")},
        {
            listing.strategy_id: [
                LiveSeat(Decimal("50"), Decimal("1000")),
                LiveSeat(Decimal("10"), Decimal("200")),
            ]
        },
    )

    [strategy] = await ReadPublicStrategies(source, brake=False).read_all()

    assert strategy.listing == listing
    assert strategy.record.closed_trade_count == 1
    assert strategy.record.total_return == Decimal("0.1")
    assert strategy.live_subscribers == 2
    assert strategy.capital == Decimal("520")


async def test_each_strategy_reads_its_own_signals_and_seats_in_the_listed_order() -> None:
    first, second = _listing(), _listing()
    source = _Source(
        [first, second],
        {first.strategy_id: _round_trip("100", "110"), second.strategy_id: []},
        {second.strategy_id: [LiveSeat(Decimal("100"), Decimal("70"))]},
    )

    answer = await ReadPublicStrategies(source, brake=False).read_all()

    assert [each.listing for each in answer] == [first, second]
    assert [each.record.closed_trade_count for each in answer] == [1, 0]
    assert [each.live_subscribers for each in answer] == [0, 1]
    assert [each.capital for each in answer] == [Decimal(0), Decimal("70")]


async def test_a_strategy_nobody_signals_or_holds_reads_zero() -> None:
    source = _Source([_listing()])

    [strategy] = await ReadPublicStrategies(source, brake=False).read_all()

    assert strategy.record.closed_trade_count == 0
    assert strategy.record.total_return == Decimal(0)
    assert strategy.live_subscribers == 0
    assert strategy.capital == Decimal(0)


async def test_under_the_brake_nobody_trades_live_and_the_capital_is_absent() -> None:
    listing = _listing()
    source = _Source(
        [listing],
        {listing.strategy_id: _round_trip("100", "110")},
        {listing.strategy_id: [LiveSeat(Decimal("50"), Decimal("1000"))]},
    )

    [strategy] = await ReadPublicStrategies(source, brake=True).read_all()

    assert strategy.live_subscribers == 0
    assert strategy.capital is None
    assert strategy.record.closed_trade_count == 1
    assert [name for name, _ in source.calls] == ["listings", "signals"]


async def test_every_listed_strategy_is_asked_about_in_one_call_each() -> None:
    first, second = _listing(), _listing()
    source = _Source([first, second])

    await ReadPublicStrategies(source, brake=False).read_all()

    ids = (first.strategy_id, second.strategy_id)
    assert source.calls == [("listings", ()), ("signals", ids), ("live_seats", ids)]


async def test_nothing_listed_asks_for_nothing_else() -> None:
    source = _Source()

    assert await ReadPublicStrategies(source, brake=False).read_all() == ()
    assert [name for name, _ in source.calls] == ["listings"]


async def test_one_strategy_reads_as_it_does_on_the_list() -> None:
    listing, other = _listing(), _listing()
    source = _Source(
        [other, listing],
        {listing.strategy_id: _round_trip("100", "90")},
        {listing.strategy_id: [LiveSeat(Decimal("25"), Decimal("400"))]},
    )

    strategy = await ReadPublicStrategies(source, brake=False).read_one(listing.strategy_id)

    assert strategy is not None
    assert strategy.listing == listing
    assert strategy.record.total_return == Decimal("-0.1")
    assert strategy.live_subscribers == 1
    assert strategy.capital == Decimal("100")
    ids = (listing.strategy_id,)
    assert source.calls == [("listing", ids), ("signals", ids), ("live_seats", ids)]


async def test_a_strategy_not_on_the_list_is_none_and_asks_for_nothing_else() -> None:
    source = _Source([_listing()])
    missing = uuid4()

    assert await ReadPublicStrategies(source, brake=False).read_one(missing) is None
    assert source.calls == [("listing", (missing,))]
