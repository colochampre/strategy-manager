"""``ReadMyTrades``: the signed-in user's CLOSED operations across every pool
they hold ledger rows in, newest close first, in offset pages (panel-redesign
RD.4a, the panel's My trades page).

**Same derivation as a strategy's list.** Each pool is read through
``AllocationFillsSourcePort.pool_fills`` and each strategy's slice of it goes
through ``strategy_groups``, ``derive_trades`` and the rehearsal merge of
``ReadStrategyTrades``, so a row here carries the figures the strategy's own
list shows for it. Rehearsal operations are included and flagged.

**Rule 7.** Pools are read one at a time and their rows are only concatenated:
nothing is added across pools, and each row carries its own currency.

**Filters, then the total.** ``total`` counts every row that passes the filters,
before ``offset`` and ``limit``. ``strategies`` and ``exchanges`` describe the
user's closed operations with NO filter applied, so the panel's choices do not
shrink as the filters narrow.

**Cost.** The figures and the close causes are derived for the rows of the page
only; the closed operations of every pool are derived to count and order them,
as a strategy's list does.

Logging: as ``ReadStrategyTrades`` (it reuses its WARNING lines for unresolved
allocations, mixed allocations and figures that cannot be derived). Silent
otherwise; no price, quantity or fee is ever logged.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import (
    AllocationFillsSourcePort,
    MyTradesSourcePort,
    TradeStrategyFacts,
)
from strategy_manager.performance.application.read_strategy_trades import (
    ReadStrategyTrades,
    log_underivable,
)
from strategy_manager.performance.application.scope import (
    pool_label,
    require_live_only,
    strategy_groups,
)
from strategy_manager.performance.domain.close_cause import CloseCause, close_cause_of
from strategy_manager.performance.domain.closed_trade import ClosedTrade, FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.performance.domain.operation import OperationFigures, operation_figures
from strategy_manager.shared.domain.errors import DomainError, InvariantViolation

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class InvalidMyTradesRequest(DomainError):
    """The page, or the filter, is not one this read can serve."""


@dataclass(frozen=True, slots=True)
class MyTrade:
    """A closed operation, its strategy, whether it is a rehearsal one, its
    figures (``None`` when they cannot be derived: never zero) and its cause."""

    trade: ClosedTrade
    strategy: TradeStrategyFacts
    rehearsal: bool
    figures: OperationFigures | None
    close_cause: CloseCause


@dataclass(frozen=True, slots=True)
class MyTradesPage:
    trades: tuple[MyTrade, ...]
    total: int
    strategies: tuple[TradeStrategyFacts, ...]
    exchanges: tuple[str, ...]


def _key(trade: ClosedTrade) -> tuple[datetime, int]:
    return (trade.closed_at, trade.allocation_id.int)


class ReadMyTrades:
    def __init__(self, fills: AllocationFillsSourcePort, source: MyTradesSourcePort) -> None:
        self._fills = fills
        self._source = source

    async def read(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        closed_since: datetime | None = None,
        strategy_id: UUID | None = None,
        exchange: str | None = None,
    ) -> MyTradesPage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidMyTradesRequest(f"limit must be 1..{MAX_PAGE_SIZE}, got {limit}")
        if offset < 0:
            raise InvalidMyTradesRequest(f"offset must be 0 or more, got {offset}")
        if closed_since is not None and (
            closed_since.tzinfo is None or closed_since.utcoffset() is None
        ):
            raise InvalidMyTradesRequest("closed_since has no time zone")

        operations: list[tuple[ClosedTrade, bool]] = []
        groups_of: dict[UUID, list[FillGroup]] = defaultdict(list)
        pool_of: dict[UUID, PoolKey] = {}
        for pool in await self._source.pools_with_fills(user_id):
            await self._derive_pool(user_id, pool, operations, groups_of, pool_of)

        facts = await self._source.strategy_facts(
            user_id, sorted({trade.strategy_id for trade, _ in operations}, key=str)
        )
        for trade, _ in operations:
            if trade.strategy_id not in facts:
                raise InvariantViolation(
                    f"allocation {trade.allocation_id} names strategy {trade.strategy_id}, "
                    "which the strategy read does not know"
                )

        listed = [
            (trade, rehearsal)
            for trade, rehearsal in operations
            if (closed_since is None or trade.closed_at >= closed_since)
            and (strategy_id is None or trade.strategy_id == strategy_id)
            and (exchange is None or trade.exchange == exchange)
        ]
        listed.sort(key=lambda op: _key(op[0]), reverse=True)
        page = listed[offset : offset + limit]

        kinds = await self._source.close_event_kinds(
            user_id, [trade.allocation_id for trade, _ in page]
        )
        trades = []
        for trade, rehearsal in page:
            groups = groups_of[trade.allocation_id]
            figures = operation_figures(groups, trade.direction)
            if figures is None:
                log_underivable(pool_of[trade.allocation_id], trade.strategy_id, trade, groups)
            trades.append(
                MyTrade(
                    trade=trade,
                    strategy=facts[trade.strategy_id],
                    rehearsal=rehearsal,
                    figures=figures,
                    close_cause=close_cause_of(kinds.get(trade.allocation_id)),
                )
            )
        return MyTradesPage(
            trades=tuple(trades),
            total=len(listed),
            strategies=tuple(
                sorted(
                    (facts[sid] for sid in {trade.strategy_id for trade, _ in operations}),
                    key=lambda s: (s.name, str(s.strategy_id)),
                )
            ),
            exchanges=tuple(sorted({trade.exchange for trade, _ in operations})),
        )

    async def _derive_pool(
        self,
        user_id: UUID,
        pool: PoolKey,
        operations: list[tuple[ClosedTrade, bool]],
        groups_of: dict[UUID, list[FillGroup]],
        pool_of: dict[UUID, PoolKey],
    ) -> None:
        """One pool's closed operations, derived strategy by strategy exactly as
        ``ReadStrategyTrades`` does, appended to ``operations``."""
        pool_fills = await self._fills.pool_fills(user_id, pool)
        strategy_ids = sorted(
            {g.strategy_id for g in pool_fills.groups}
            | {g.strategy_id for g in pool_fills.rehearsal_groups},
            key=str,
        )
        for strategy_id in strategy_ids:
            live_groups = strategy_groups(pool, strategy_id, pool_fills.groups)
            require_live_only(live_groups)
            derived = derive_trades(live_groups)
            unresolved = list(derived.unresolved_allocation_ids)
            closed = [(trade, False) for trade in derived.closed]

            rehearsal_groups, rehearsal_derived = ReadStrategyTrades.rehearsal_operations(
                pool, strategy_id, live_groups, pool_fills.rehearsal_groups
            )
            unresolved += rehearsal_derived.unresolved_allocation_ids
            closed += [(trade, True) for trade in rehearsal_derived.closed]
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
            operations += closed
            for trade, _ in closed:
                pool_of[trade.allocation_id] = pool
            for group in listed_groups:
                groups_of[group.allocation_id].append(group)
