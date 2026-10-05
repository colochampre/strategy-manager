"""``ReadOperationFills``: the individual fills of one operation, in the order
they happened (design.md, addendum "a strategy's operations", sections D, E, G).

The detail view of an operation shows each fill's time, side, price, quantity,
fee and fee currency. This read serves exactly the stored values: it derives
nothing, averages nothing and converts nothing (CLAUDE.md rule 7), so it needs no
``base_currency_of`` and cannot fail on a symbol. It takes no lock and writes
nothing.

**Capped, not paged.** An operation of this system has a handful of fills, so the
cap bounds a response and does not page one. The read asks the source for
``MAX_OPERATION_FILLS + 1``; when it gets them it serves the first 200 and says
``truncated``, so the flag turns true only when a 201st fill exists.

**Unknown, foreign and empty are one answer.** The source is asked for the
strategy AND the allocation together, so an allocation of another strategy
answers nothing, the same as an id that does not exist and an allocation that
never had a fill. All three raise ``UnknownOperation`` and the caller cannot tell
them apart: the read does not say whether an id exists under another strategy.

**The pool is checked after the read, never in the WHERE.** A pool predicate
would drop a fill written under another pool and leave a shorter list with no
trace. Reading by allocation and strategy and then refusing a foreign-pool fill
is the rule ``scope.require_single_pool`` applies to the list: the read raises
``InvariantViolation`` and returns nothing.

**A mixed allocation** (fills of both origins) is served whole, each fill with
its own ``rehearsal`` flag, so the one place a mixed allocation can be looked at
hides nothing; one WARNING names it.

Logging: ``WARNING`` with the strategy id and the allocation id for an unknown
operation and for a mixed one, and with the cap for a truncated one. No price,
quantity or fee is ever logged.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import OperationFillsSourcePort
from strategy_manager.performance.domain.operation import OperationFill
from strategy_manager.shared.domain.errors import DomainError, InvariantViolation

logger = logging.getLogger(__name__)

MAX_OPERATION_FILLS = 200


class UnknownOperation(DomainError):
    """No fill carries both the strategy's id and the allocation's id."""


@dataclass(frozen=True, slots=True)
class OperationFills:
    """``fills`` is never empty; ``truncated`` says a 201st fill exists."""

    allocation_id: UUID
    fills: tuple[OperationFill, ...]
    truncated: bool


def _require_pool(pool: PoolKey, fills: tuple[OperationFill, ...]) -> None:
    for fill in fills:
        if (
            fill.exchange != pool.exchange.value
            or fill.venue != pool.venue.value
            or fill.settlement_currency != pool.settlement_currency.value
        ):
            raise InvariantViolation(
                f"the fills source returned a fill of pool ({fill.exchange}, {fill.venue}, "
                f"{fill.settlement_currency}) for an operation of ({pool.exchange.value}, "
                f"{pool.venue.value}, {pool.settlement_currency.value}); pools are never "
                "blended (CLAUDE.md rule 7)"
            )


class ReadOperationFills:
    def __init__(self, source: OperationFillsSourcePort) -> None:
        self._source = source

    async def read(self, strategy_id: UUID, pool: PoolKey, allocation_id: UUID) -> OperationFills:
        found = tuple(
            await self._source.operation_fills(strategy_id, allocation_id, MAX_OPERATION_FILLS + 1)
        )
        if not found:
            logger.warning(
                "performance strategy %s allocation %s: no fill carries both ids, so there "
                "is no such operation",
                strategy_id,
                allocation_id,
            )
            raise UnknownOperation(f"no operation {allocation_id} with fills of {strategy_id}")

        _require_pool(pool, found)

        truncated = len(found) > MAX_OPERATION_FILLS
        served = found[:MAX_OPERATION_FILLS]
        if truncated:
            logger.warning(
                "performance strategy %s allocation %s: more than %d fills, the first %d "
                "are served",
                strategy_id,
                allocation_id,
                MAX_OPERATION_FILLS,
                MAX_OPERATION_FILLS,
            )
        if len({fill.rehearsal for fill in served}) > 1:
            logger.warning(
                "performance strategy %s allocation %s: the fills hold both live and "
                "rehearsal origins, each is served with its own flag",
                strategy_id,
                allocation_id,
            )
        return OperationFills(allocation_id=allocation_id, fills=served, truncated=truncated)
