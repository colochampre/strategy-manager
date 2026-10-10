"""Unit tests for ``PreviewShare``: one read of the sizing port, then the pure
domain functions (design.md, unit 12f addendum, sections C2 and H; spec: admin-api
"The Share Preview Route Serves The Amount A Share Asks For"; tasks.md 12f.9.10).

The port is a fake held in this file. ``PreviewShare`` has no lock, no commit and no
clock of its own, so nothing here needs a database or a time.

**Amount of the total, not of what is free.** The port's snapshot has no
``available`` field at all (it is read-only by shape and carries only what a display
may use), so the use case cannot compute from it; the test of that rule here pins the
outcome, and the adapter and the route tests (12f.9.11, 12f.9.12) carry the mutation
that selects the wrong column.
"""

from datetime import UTC, datetime
from decimal import Decimal

from strategy_manager.allocation.application.allocate_capital import UnknownPoolError
from strategy_manager.allocation.application.ports import PoolSizing, SizingSnapshot
from strategy_manager.allocation.application.preview_share import PreviewShare
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.share_preview import ShareAmount
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
OBSERVED_AT = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)


class FakeSizing:
    """A ``PoolSizingPort`` that answers one prepared value and records its reads."""

    def __init__(self, answer: PoolSizing | None) -> None:
        self.answer = answer
        self.reads: list[tuple[str, str, str]] = []

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolSizing | None:
        self.reads.append((exchange, venue, settlement_currency))
        return self.answer


def _sizing(total: str = "1000", *, stale: bool = False, minimum: str = "5") -> PoolSizing:
    return PoolSizing(
        min_order_size=Decimal(minimum),
        snapshot=SizingSnapshot(total=Decimal(total), observed_at=OBSERVED_AT, stale=stale),
    )


async def test_a_snapshot_gives_the_exact_amount_and_the_hundred_steps() -> None:
    preview = await PreviewShare(FakeSizing(_sizing("1000"))).preview(POOL, Decimal("33.5"))

    assert preview.pool == POOL
    assert preview.pool_minimum == Decimal("5")
    assert preview.balance == SizingSnapshot(Decimal("1000"), OBSERVED_AT, False)
    assert preview.exact == ShareAmount(Decimal("33.5"), Decimal("335"), False)
    assert len(preview.steps) == 100
    assert preview.steps[0] == ShareAmount(Decimal(1), Decimal("10"), False)
    assert preview.steps[-1] == ShareAmount(Decimal(100), Decimal("1000"), False)


async def test_the_amount_comes_from_the_total_not_from_what_is_available() -> None:
    """The pool holds 1000, of which 400 is free: a share of 10 asks for 100. The
    port cannot hand over the free 400 (see this module's docstring)."""
    preview = await PreviewShare(FakeSizing(_sizing("1000"))).preview(POOL, Decimal("10"))

    assert preview.exact is not None
    assert preview.exact.amount == Decimal("100")


async def test_a_stale_snapshot_is_served_and_marked() -> None:
    """The worker's reader refuses a stale snapshot; a display shows it and says so."""
    preview = await PreviewShare(FakeSizing(_sizing("1000", stale=True))).preview(
        POOL, Decimal("10")
    )

    assert preview.balance is not None
    assert preview.balance.stale is True
    assert preview.exact is not None
    assert preview.exact.amount == Decimal("100")
    assert len(preview.steps) == 100


async def test_no_snapshot_gives_no_balance_no_exact_amount_no_steps_and_never_a_zero() -> None:
    sizing = PoolSizing(min_order_size=Decimal("5"), snapshot=None)

    preview = await PreviewShare(FakeSizing(sizing)).preview(POOL, Decimal("33.5"))

    assert preview.balance is None
    assert preview.exact is None
    assert preview.steps == ()


async def test_a_pool_nothing_has_synced_still_carries_its_minimum() -> None:
    sizing = PoolSizing(min_order_size=Decimal("5"), snapshot=None)

    preview = await PreviewShare(FakeSizing(sizing)).preview(POOL, Decimal("33.5"))

    assert preview.pool_minimum == Decimal("5")


async def test_the_stored_share_is_the_default_and_an_asked_share_replaces_it() -> None:
    """``preview`` previews the share it is handed: the route hands over the
    strategy's stored share, or the asked one in its place. Only ``exact`` follows
    it; the hundred steps are the same table either way."""
    use_case = PreviewShare(FakeSizing(_sizing("1000")))

    stored = await use_case.preview(POOL, Decimal("33.5"))
    asked = await use_case.preview(POOL, Decimal("12.34"))

    assert stored.exact == ShareAmount(Decimal("33.5"), Decimal("335"), False)
    assert asked.exact == ShareAmount(Decimal("12.34"), Decimal("123.4"), False)
    assert stored.steps == asked.steps


async def test_the_port_is_read_once() -> None:
    fake = FakeSizing(_sizing("1000"))

    await PreviewShare(fake).preview(POOL, Decimal("33.5"))

    assert fake.reads == [("bybit", "usdt-m", "USDT")]


async def test_a_pool_with_no_row_raises_the_modules_invariant_error() -> None:
    """A strategy cannot be registered on a pool that does not exist, so a port that
    answers nothing is a fault in stored data, told to the caller as the allocation
    module's own misconfiguration error. The exception is captured and asserted on
    its type, so a use case that raises nothing fails an assertion."""
    captured: Exception | None = None

    try:
        await PreviewShare(FakeSizing(None)).preview(POOL, Decimal("33.5"))
    except Exception as exc:  # noqa: BLE001
        captured = exc

    assert type(captured) is UnknownPoolError
    assert "bybit" in str(captured)
    assert "usdt-m" in str(captured)
    assert "USDT" in str(captured)
