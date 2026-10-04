"""``ReadStrategyTrades``: one strategy's closed trades, newest first, in keyset
pages (design.md section 14 "Pagination"; tasks.md 3d.4, 3d.5).

**The order and the cursor.** Trades sort by ``(closed_at, allocation_id)``
DESCENDING, and a page resumes strictly after the ``TradeCursor`` (the
``closed_at`` and ``allocation_id`` of the last trade served): the next page
holds the trades whose pair is lexicographically smaller than the cursor's.
Never ``closed_at`` alone: two trades that close in the same millisecond (the
"+1ms" lesson) would be dropped by ``closed_at < c`` or repeated by
``closed_at <= c`` when a page ends between them. Ordering is by the UUID's
integer value, which is the byte order PostgreSQL uses for ``uuid``.

**Wire form** (for PR 7): two query parameters, ``before_closed_at`` (ISO-8601
with its time zone and full microseconds, ``timestamptz``'s own precision) and
``before_allocation_id`` (UUID text). ``TradeCursor`` is the two together, so
"half a cursor" cannot be represented here and is refused by the endpoint as a
422. A ``closed_at`` with no time zone is refused (``InvalidPageRequest``): it
cannot be ordered against ``timestamptz`` without guessing the zone.

**A trade that closes between two page reads.** The cursor is a position, not
a snapshot. A trade that closes now has the newest ``closed_at`` of all, so it
sorts before page 1: page 2 from the cursor is unchanged, nothing is repeated
and nothing is lost, and the new trade shows on the next read from the top. A
trade that lands AFTER the cursor in the ordering (a booked close dated
earlier) is reached and served once when the walk arrives at it. Only a trade
that lands BEFORE the cursor in the ordering, having not existed when that
part was served, is missed by the walk in progress until it is restarted from
the top. That is the accepted limit of keyset paging over a live ledger.

**Where the paging happens.** Over the derived trades, in Python, not in SQL.
"Closed" is not a column: it is net base quantity exactly zero under the
base-fee rule (``derive_trade``), and the base currency of a symbol is a domain
rule (``base_currency_of``) SQL does not have. A SQL keyset would have to
replicate that rule and could disagree with the pool figures. See design.md
section 11, "As built (PR 6c)", for what bounds the work.

Logging: ``WARNING`` with the ids for an allocation whose closure cannot be
tested (it is otherwise missing from the list with no trace); silent
otherwise. The steady-state exclusions belong to the performance report, not
to every page of a list.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.performance.application.ports import (
    AllocationFillsSourcePort,
    RehearsalPricingSourcePort,
)
from strategy_manager.performance.application.scope import (
    pool_label,
    require_live_only,
    strategy_groups,
)
from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction, FillGroup
from strategy_manager.performance.domain.curve import trade_return
from strategy_manager.performance.domain.derive_trade import DerivedTrades, derive_trades
from strategy_manager.performance.domain.operation import (
    BUY,
    SELL,
    OperationFees,
    OperationFigures,
    RehearsalPricing,
    classify_rehearsal_pricing,
    operation_fees,
    operation_figures,
    sides_overlap,
)
from strategy_manager.shared.domain.errors import DomainError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class InvalidPageRequest(DomainError):
    """The page size or the cursor is not one this read can serve."""


@dataclass(frozen=True, slots=True)
class TradeCursor:
    """The position after the last trade served: its ``closed_at`` and its
    allocation id, together."""

    closed_at: datetime
    allocation_id: UUID

    def __post_init__(self) -> None:
        if self.closed_at.tzinfo is None or self.closed_at.utcoffset() is None:
            raise InvalidPageRequest(
                f"cursor closed_at {self.closed_at.isoformat()} has no time zone; it "
                "cannot be ordered against timestamptz values without guessing one"
            )


@dataclass(frozen=True, slots=True)
class TradeItem:
    """A closed trade and its return on the pool's capital at open (``None``
    when the trade has no capital at open), whether it is a rehearsal operation,
    its fees and its figures (``None`` when they cannot be derived: never zero)."""

    trade: ClosedTrade
    value: Decimal | None
    rehearsal: bool
    fees: OperationFees
    figures: OperationFigures | None
    pricing: RehearsalPricing | None


@dataclass(frozen=True, slots=True)
class TradesPage:
    """``next_cursor`` is ``None`` on the last page."""

    trades: tuple[TradeItem, ...]
    next_cursor: TradeCursor | None


def _key(trade: ClosedTrade) -> tuple[datetime, int]:
    return (trade.closed_at, trade.allocation_id.int)


def _log_underivable(
    pool: PoolKey, strategy_id: UUID, trade: ClosedTrade, groups: list[FillGroup]
) -> None:
    """Why an operation's entry price, exit price and size are null. The domain
    answers only ``None``, so the causes are told apart here, one line each
    (design section G). Ids, the pool label, sides and market keys only: no
    price, quantity or fee is ever logged."""
    markets = sorted({market_key(group.symbol) for group in groups})
    if len(markets) > 1:
        logger.warning(
            "performance %s strategy %s allocation %s: entry price, exit price and size "
            "not derived, the fills name more than one market: %s",
            pool_label(pool),
            strategy_id,
            trade.allocation_id,
            ", ".join(markets),
        )
        return
    opening_side = BUY if trade.direction is Direction.LONG else SELL
    unreadable: list[str] = []
    for name, on_side in (
        ("opening", [g for g in groups if g.side == opening_side]),
        ("closing", [g for g in groups if g.side != opening_side]),
    ):
        quantity = sum((g.quantity for g in on_side), Decimal(0))
        notional = sum((g.notional for g in on_side), Decimal(0))
        if quantity <= 0 or notional <= 0:
            unreadable.append(name)
    logger.warning(
        "performance %s strategy %s allocation %s: entry price, exit price and size not "
        "derived, the %s side has no quantity or notional above zero",
        pool_label(pool),
        strategy_id,
        trade.allocation_id,
        " and ".join(unreadable),
    )


class ReadStrategyTrades:
    def __init__(
        self, fills: AllocationFillsSourcePort, pricing: RehearsalPricingSourcePort
    ) -> None:
        self._fills = fills
        self._pricing = pricing

    async def read(
        self,
        strategy_id: UUID,
        pool: PoolKey,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        before: TradeCursor | None = None,
        include_rehearsal: bool = False,
    ) -> TradesPage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidPageRequest(f"limit must be 1..{MAX_PAGE_SIZE}, got {limit}")

        pool_fills = await self._fills.pool_fills(pool)
        live_groups = strategy_groups(pool, strategy_id, pool_fills.groups)
        require_live_only(live_groups)
        derived = derive_trades(live_groups)
        unresolved = list(derived.unresolved_allocation_ids)
        operations: list[tuple[ClosedTrade, bool]] = [(t, False) for t in derived.closed]
        listed_groups = live_groups

        if include_rehearsal:
            rehearsal_groups, rehearsal_derived = self._rehearsal_operations(
                pool, strategy_id, live_groups, pool_fills.rehearsal_groups
            )
            unresolved += rehearsal_derived.unresolved_allocation_ids
            operations += [(t, True) for t in rehearsal_derived.closed]
            listed_groups = live_groups + rehearsal_groups

        if unresolved:
            logger.warning(
                "performance %s strategy %s: %d allocation(s) skipped because the symbol "
                "has no base currency in the pool's settlement currency, so they are "
                "missing from the trade list: %s",
                pool_label(pool),
                strategy_id,
                len(unresolved),
                ", ".join(str(a) for a in unresolved),
            )

        ordered = sorted(operations, key=lambda op: _key(op[0]), reverse=True)
        if before is not None:
            after = (before.closed_at, before.allocation_id.int)
            ordered = [op for op in ordered if _key(op[0]) < after]

        page = ordered[:limit]
        next_cursor = (
            TradeCursor(page[-1][0].closed_at, page[-1][0].allocation_id)
            if len(ordered) > limit
            else None
        )

        # Only the rows of the page are measured: the figures are a display
        # derivation, so their cost follows ``limit`` and not the pool.
        page_ids = {trade.allocation_id for trade, _ in page}
        page_groups: dict[UUID, list[FillGroup]] = defaultdict(list)
        for group in listed_groups:
            if group.allocation_id in page_ids:
                page_groups[group.allocation_id].append(group)

        pricing = await self._classify(
            pool, strategy_id, [trade for trade, rehearsal in page if rehearsal]
        )
        return TradesPage(
            trades=tuple(
                self._item(
                    pool,
                    strategy_id,
                    trade,
                    rehearsal,
                    page_groups[trade.allocation_id],
                    pricing.get(trade.allocation_id),
                )
                for trade, rehearsal in page
            ),
            next_cursor=next_cursor,
        )

    async def _classify(
        self, pool: PoolKey, strategy_id: UUID, rehearsal_trades: list[ClosedTrade]
    ) -> dict[UUID, RehearsalPricing]:
        """How each rehearsal row of the page was priced, from ONE call to the
        pricing source with the ids of those rows only, and none at all when the
        page holds no rehearsal row (design section E, step 6).

        A row the source has no facts for reads ``UNDETERMINED`` and one WARNING
        names it. The rows that read ``UNDETERMINED`` are counted in one INFO line
        per page: a steady state if the simulated exchange prices a fill at
        anything but the stored alert price, so a line per row would be noise."""
        if not rehearsal_trades:
            return {}
        facts = await self._pricing.pricing_facts(
            pool, strategy_id, [trade.allocation_id for trade in rehearsal_trades]
        )
        pricing: dict[UUID, RehearsalPricing] = {}
        missing: list[UUID] = []
        for trade in rehearsal_trades:
            known = facts.get(trade.allocation_id)
            if known is None:
                missing.append(trade.allocation_id)
                pricing[trade.allocation_id] = RehearsalPricing.UNDETERMINED
            else:
                pricing[trade.allocation_id] = classify_rehearsal_pricing(trade.direction, known)
        if missing:
            logger.warning(
                "performance %s strategy %s: no pricing facts for %d rehearsal "
                "operation(s), read as undetermined: %s",
                pool_label(pool),
                strategy_id,
                len(missing),
                ", ".join(str(a) for a in missing),
            )
        undetermined = sum(1 for kind in pricing.values() if kind is RehearsalPricing.UNDETERMINED)
        if undetermined:
            logger.info(
                "performance %s strategy %s: %d rehearsal operation(s) on this page have "
                "an undetermined fill price",
                pool_label(pool),
                strategy_id,
                undetermined,
            )
        return pricing

    @staticmethod
    def _item(
        pool: PoolKey,
        strategy_id: UUID,
        trade: ClosedTrade,
        rehearsal: bool,
        groups: list[FillGroup],
        pricing: RehearsalPricing | None,
    ) -> TradeItem:
        figures = operation_figures(groups, trade.direction)
        if figures is None:
            _log_underivable(pool, strategy_id, trade, groups)
        if sides_overlap(groups, trade.direction):
            logger.warning(
                "performance %s strategy %s allocation %s: the opening side's last fill is "
                "not before the closing side's first fill, so which side opened rests on "
                "the tie-break alone",
                pool_label(pool),
                strategy_id,
                trade.allocation_id,
            )
        return TradeItem(
            trade,
            trade_return(trade),
            rehearsal=rehearsal,
            fees=operation_fees(groups),
            figures=figures,
            pricing=pricing,
        )

    @staticmethod
    def _rehearsal_operations(
        pool: PoolKey,
        strategy_id: UUID,
        live_groups: tuple[FillGroup, ...],
        rehearsal_groups: tuple[FillGroup, ...],
    ) -> tuple[tuple[FillGroup, ...], DerivedTrades]:
        """The rehearsal groups of the strategy, minus every allocation that also
        has a live group, and the closed operations derived from them: a mixed
        allocation is listed once, from its real fills, and one WARNING names it
        (design section C)."""
        scoped = strategy_groups(pool, strategy_id, rehearsal_groups)
        live_ids = {group.allocation_id for group in live_groups}
        mixed = sorted({g.allocation_id for g in scoped if g.allocation_id in live_ids}, key=str)
        if mixed:
            logger.warning(
                "performance %s strategy %s: %d allocation(s) hold both live and rehearsal "
                "fills; each is listed once, from its live fills: %s",
                pool_label(pool),
                strategy_id,
                len(mixed),
                ", ".join(str(a) for a in mixed),
            )
        kept = tuple(g for g in scoped if g.allocation_id not in live_ids)
        return kept, derive_trades(kept)
