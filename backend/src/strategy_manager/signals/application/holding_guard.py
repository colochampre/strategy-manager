"""``HoldingGuard``: the Existing-Position Guard (spec: capital-allocation §
Existing-Position Guard) run at the top of ``_handle_consumes``, before any
capital is allocated (design.md § "Guard order").

**Precedence, in order:**

1. The signal already owns a reservation (a retry past the point
   ``AllocateCapital`` ran) -- resume, skip every other check.
2. The strategy has execution work in flight on this symbol -- DEFER by
   seeding an ``OpenAfterClose`` continuation that polls the database on its
   own cadence (design.md § S5, amending S2), UNLESS the signal is already
   older than ``delayed_open_max_signal_age_seconds``, in which case give up
   and refuse with a WARNING instead of waiting forever. Deferring replaced
   raising ``HoldingNotSettledYet`` into the queue's failure backoff: that
   backoff's own arithmetic (30/60/120/240/480s) outlasts the age bound by
   its fifth retry, so a signal it never records as failed could still end
   as a silent FAILED job with no WARNING at all.
3. The strategy's ledger net on the symbol is zero -- proceed.
4. Otherwise the holding is divergent (ledger and venue may disagree, but
   nothing is in flight to explain it) -- read the venue's own net (the
   ONE remote call this guard makes, before the pool's advisory lock is ever
   touched) and classify it (spec: capital-allocation § Orphan
   Classification; design.md § S4). REAL, GHOST and AMBIGUOUS all refuse
   with a WARNING today -- owner decision A1 keeps REAL refused until S6
   delivers closing it, and A2 refuses AMBIGUOUS exactly like a ghost.

A refusal (``proceed=False, refused=...``) or a deferral
(``proceed=False, refused=None``) here MUST NEVER reach
``AllocateCapital.allocate()`` -- the caller is expected to check
``GuardOutcome.proceed`` before doing anything else, and to distinguish the
two by ``refused`` before deciding whether to seed a continuation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.signals.application.ports import (
    InFlightWorkPort,
    PoolKey,
    SymbolHoldingsPort,
    VenueNetPositionPort,
)
from strategy_manager.signals.domain.holding import (
    HeldAllocation,
    OrphanKind,
    classify_orphan,
    strategy_net,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    """``proceed`` True means the caller may continue toward
    ``AllocateCapital``.

    ``False`` with ``refused`` set means the signal must be refused
    outright (mirrors ``ProcessSignalResult.refused``).

    ``False`` with ``refused is None`` means DEFERRED: in-flight work exists
    but has not settled yet. ``awaited_allocation_ids`` (possibly empty --
    see ``InFlightWorkPort.submitted_closing_allocations``) names which
    allocation(s) the caller's ``OpenAfterClose`` continuation should await
    before re-running this guard from scratch via
    ``ProcessSignalHandler.open_now`` (design.md § S5, amending S2)."""

    proceed: bool
    refused: str | None = None
    awaited_allocation_ids: list[UUID] | None = None


class HoldingGuard:
    def __init__(
        self,
        holdings: SymbolHoldingsPort,
        in_flight_work: InFlightWorkPort,
        venue_net_position: VenueNetPositionPort,
        clock: ClockPort,
        delayed_open_max_signal_age_seconds: float,
    ) -> None:
        self._holdings = holdings
        self._in_flight_work = in_flight_work
        self._venue_net_position = venue_net_position
        self._clock = clock
        self._delayed_open_max_signal_age_seconds = delayed_open_max_signal_age_seconds

    async def check(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        own_reservation_id: UUID | None,
        received_at: datetime,
    ) -> GuardOutcome:
        if own_reservation_id is not None:
            return GuardOutcome(proceed=True)

        now = self._clock.now()
        if await self._in_flight_work.in_flight(pool, strategy_id, symbol, now):
            return await self._on_in_flight(pool, strategy_id, symbol, now, received_at)

        holdings = await self._holdings.symbol_holdings(pool, symbol)
        net = strategy_net(holdings, strategy_id)
        if net == 0:
            return GuardOutcome(proceed=True)

        return await self._classify_and_refuse(pool, strategy_id, symbol, holdings, net)

    async def _on_in_flight(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        now: datetime,
        received_at: datetime,
    ) -> GuardOutcome:
        age_seconds = (now - received_at).total_seconds()
        if age_seconds <= self._delayed_open_max_signal_age_seconds:
            awaited_allocation_ids = await self._in_flight_work.submitted_closing_allocations(
                pool, strategy_id, symbol
            )
            logger.info(
                "deferring open for strategy %s on %s in pool %s: work still in "
                "flight; seeding a continuation to await %s",
                strategy_id,
                symbol,
                pool,
                awaited_allocation_ids or "settlement",
            )
            return GuardOutcome(proceed=False, awaited_allocation_ids=awaited_allocation_ids)

        refused = (
            f"strategy {strategy_id} still has work in flight on {symbol} in "
            f"pool {pool} after {age_seconds:.0f}s, past the "
            f"{self._delayed_open_max_signal_age_seconds:.0f}s bound; abandoning "
            "this signal rather than retrying it forever"
        )
        logger.warning("abandoning delayed open: %s", refused)
        return GuardOutcome(proceed=False, refused=refused)

    async def _classify_and_refuse(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        net: Decimal,
    ) -> GuardOutcome:
        """The divergent branch's ONE remote call (design.md § "Every remote
        read happens before ``_lock.acquire``"), followed by classification
        (spec: capital-allocation § Orphan Classification). Every kind
        refuses today -- only ``REAL``'s ACTION (close-then-open) is S6
        scope; classifying it correctly is not."""
        pool_net = sum((holding.net_base for holding in holdings), start=Decimal("0"))
        venue_net = await self._venue_net_position.net_position(pool, symbol)
        kind = classify_orphan(net, pool_net, venue_net)

        if kind is OrphanKind.REAL:
            refused = (
                f"strategy {strategy_id} holds a REAL orphan on {symbol} in pool "
                f"{pool} (pool net {pool_net}, venue net {venue_net}); refusing "
                "until S6 closes it"
            )
        else:
            own_allocations = ", ".join(
                f"{holding.allocation_id}={holding.net_base}"
                for holding in holdings
                if holding.strategy_id == strategy_id
            )
            refused = (
                f"strategy {strategy_id} holds a {kind.value} divergent net {net} "
                f"on {symbol} in pool {pool} (allocations: {own_allocations}); "
                f"pool net {pool_net}, other strategies' net {pool_net - net}, "
                f"venue net {venue_net}; refusing"
            )
        logger.warning("refusing %s holding: %s", kind.value.lower(), refused)
        return GuardOutcome(proceed=False, refused=refused)
