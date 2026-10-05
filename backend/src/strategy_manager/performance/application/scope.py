"""Scoping and exclusion logging shared by the performance reads.

**Rule 7 and decision 1 for a strategy.** A strategy is one strategy in one
pool, so a strategy's figures are a slice of ONE pool's ledger and are never
gathered across pools. That is enforced by construction and by refusal:

- construction: a read takes the strategy AND the ``PoolKey`` it lives in, and
  asks the source for that one pool. The port has no method that reads more.
- refusal, 1: ``require_single_pool`` checks every row the source returns
  against the requested pool BEFORE the strategy filter is applied, so a
  misbehaving source is refused even for a row that would have been dropped as
  "someone else's".
- refusal, 2: ``strategy_groups`` refuses an allocation whose legs come back
  under more than one strategy id. An allocation is one reservation of one
  strategy; if it is split, deriving either half would invent an open trade or
  a wrong PnL, so nothing is derived.

**What is logged, and why at that level** (the levels PR 6b chose for read
models, unchanged): ``WARNING`` with the allocation ids for an allocation whose
symbol cannot be tested for closure (a data-integrity fault a bare count
cannot be traced from); ``INFO`` with the count for trades without capital at
open and trades with an unconverted fee (steady state, already alerted at the
cause); nothing when nothing was left out. Never ``ERROR``: only ``ERROR``
reaches the operator's alerts, and a read model fires once per page view.
"""

import logging
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.curve import Exclusions
from strategy_manager.shared.domain.errors import InvariantViolation


def pool_label(pool: PoolKey) -> str:
    return f"{pool.exchange.value}/{pool.venue.value}/{pool.settlement_currency.value}"


def require_single_pool(pool: PoolKey, groups: tuple[FillGroup, ...]) -> None:
    for group in groups:
        if (
            group.exchange != pool.exchange.value
            or group.venue != pool.venue.value
            or group.settlement_currency != pool.settlement_currency.value
        ):
            raise InvariantViolation(
                f"the fills source returned a row of pool ({group.exchange}, {group.venue}, "
                f"{group.settlement_currency}) for a read of ({pool.exchange.value}, "
                f"{pool.venue.value}, {pool.settlement_currency.value}); pools are never "
                "blended (CLAUDE.md rule 7)"
            )


def require_live_only(groups: tuple[FillGroup, ...]) -> None:
    """The second wall that keeps a rehearsal group out of every total.

    The first is by construction (the totals read ``PoolFills.groups`` and
    nothing else); this one is by refusal. A group marked rehearsal in the live
    set means the source put it in the wrong set, and any figure derived from it
    would silently mix dry-run money into real PnL, so it raises instead.
    """
    rehearsal = sorted({str(group.allocation_id) for group in groups if group.rehearsal})
    if rehearsal:
        raise InvariantViolation(
            "the fills source put rehearsal groups in the live set, for allocation(s) "
            f"{', '.join(rehearsal)}; a rehearsal fill is never part of a total"
        )


def strategy_groups(
    pool: PoolKey, strategy_id: UUID, groups: tuple[FillGroup, ...]
) -> tuple[FillGroup, ...]:
    """The aggregates of ``strategy_id``'s allocations in ``pool``.

    Raises ``InvariantViolation`` for a row of another pool (any strategy) and
    for an allocation of this strategy whose legs carry another strategy id.
    """
    require_single_pool(pool, groups)

    allocations = {g.allocation_id for g in groups if g.strategy_id == strategy_id}
    scoped = tuple(g for g in groups if g.allocation_id in allocations)
    for group in scoped:
        if group.strategy_id != strategy_id:
            raise InvariantViolation(
                f"allocation {group.allocation_id} has fills under strategy "
                f"{group.strategy_id} and under strategy {strategy_id}; an allocation "
                "belongs to exactly one strategy, so it is not derived"
            )
    return scoped


def log_exclusions(
    logger: logging.Logger,
    label: str,
    unresolved: tuple[UUID, ...],
    exclusions: Exclusions,
) -> None:
    if unresolved:
        logger.warning(
            "performance %s: %d allocation(s) skipped because the symbol has no base "
            "currency in the pool's settlement currency, so their closure cannot be "
            "tested: %s",
            label,
            len(unresolved),
            ", ".join(str(a) for a in unresolved),
        )
    if exclusions.no_capital_at_open:
        logger.info(
            "performance %s: %d closed trade(s) with no capital at open are in the PnL "
            "amounts but not in the curve",
            label,
            exclusions.no_capital_at_open,
        )
    if exclusions.unconverted_fee:
        logger.info(
            "performance %s: %d closed trade(s) have an unconverted fee (a third "
            "currency); their PnL omits it",
            label,
            exclusions.unconverted_fee,
        )
