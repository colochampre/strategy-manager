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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import AllocationFillsSourcePort
from strategy_manager.performance.application.scope import (
    pool_label,
    require_live_only,
    strategy_groups,
)
from strategy_manager.performance.domain.closed_trade import ClosedTrade, FillGroup
from strategy_manager.performance.domain.curve import trade_return
from strategy_manager.performance.domain.derive_trade import DerivedTrades, derive_trades
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
    when the trade has no capital at open)."""

    trade: ClosedTrade
    value: Decimal | None
    rehearsal: bool = False


@dataclass(frozen=True, slots=True)
class TradesPage:
    """``next_cursor`` is ``None`` on the last page."""

    trades: tuple[TradeItem, ...]
    next_cursor: TradeCursor | None


def _key(trade: ClosedTrade) -> tuple[datetime, int]:
    return (trade.closed_at, trade.allocation_id.int)


class ReadStrategyTrades:
    def __init__(self, fills: AllocationFillsSourcePort) -> None:
        self._fills = fills

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

        if include_rehearsal:
            rehearsal_derived = self._rehearsal_operations(
                pool, strategy_id, live_groups, pool_fills.rehearsal_groups
            )
            unresolved += rehearsal_derived.unresolved_allocation_ids
            operations += [(t, True) for t in rehearsal_derived.closed]

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
        return TradesPage(
            trades=tuple(
                TradeItem(trade, trade_return(trade), rehearsal=rehearsal)
                for trade, rehearsal in page
            ),
            next_cursor=next_cursor,
        )

    @staticmethod
    def _rehearsal_operations(
        pool: PoolKey,
        strategy_id: UUID,
        live_groups: tuple[FillGroup, ...],
        rehearsal_groups: tuple[FillGroup, ...],
    ) -> DerivedTrades:
        """The closed rehearsal operations of the strategy, minus every allocation
        that also has a live group: a mixed allocation is listed once, from its
        real fills, and one WARNING names it (design section C)."""
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
        return derive_trades(tuple(g for g in scoped if g.allocation_id not in live_ids))
