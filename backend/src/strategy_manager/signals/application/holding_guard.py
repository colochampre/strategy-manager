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
   Classification; design.md § S4). GHOST and AMBIGUOUS refuse with a
   WARNING (owner decision A2 refuses AMBIGUOUS exactly like a ghost).
   REAL is never refused: it is reported via
   ``GuardOutcome.real_orphan_holdings`` instead, because this guard only
   classifies -- it takes no action and touches nothing outside a read
   (see below). The caller (``ProcessSignalHandler._handle_consumes``)
   is what actually closes it, through ``CloseOrphans`` (spec:
   capital-allocation § Real-Orphan Resolution via Close-Then-Open;
   design.md § S6, owner decision 3: close the REAL orphan, then open).

A refusal (``proceed=False, refused=...``), a deferral (``proceed=False,
refused=None, real_orphan_holdings=None``) or a REAL-orphan report
(``proceed=False, real_orphan_holdings=[...]``) here MUST NEVER reach
``AllocateCapital.allocate()`` -- the caller is expected to check
``GuardOutcome.proceed`` before doing anything else, and to distinguish the
three by ``refused``/``real_orphan_holdings`` before deciding what to do
next.
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

    ``False`` with ``refused is None`` and ``real_orphan_holdings is None``
    means DEFERRED: in-flight work exists but has not settled yet.
    ``awaited_allocation_ids`` (possibly empty -- see
    ``InFlightWorkPort.submitted_closing_allocations``) names which
    allocation(s) the caller's ``OpenAfterClose`` continuation should await
    before re-running this guard from scratch via
    ``ProcessSignalHandler.open_now`` (design.md § S5, amending S2).

    ``False`` with ``real_orphan_holdings`` set (never empty -- see
    ``HeldAllocation``'s own guarantee) means the divergent holding
    classified REAL (spec: capital-allocation § Orphan Classification;
    design.md § S4/S6): the strategy's own non-zero allocations on this
    market, for the caller to close via ``CloseOrphans`` before deferring
    the open the same way the in-flight branch does."""

    proceed: bool
    refused: str | None = None
    awaited_allocation_ids: list[UUID] | None = None
    real_orphan_holdings: list[HeldAllocation] | None = None


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

        return await self._classify_divergence(pool, strategy_id, symbol, holdings, net)

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

    async def _classify_divergence(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        net: Decimal,
    ) -> GuardOutcome:
        """The divergent branch's ONE remote call (design.md § "Every remote
        read happens before ``_lock.acquire``"), followed by classification
        (spec: capital-allocation § Orphan Classification). GHOST and
        AMBIGUOUS refuse here; REAL does not -- it is reported to the
        caller instead (design.md § S6), which is the one that actually
        closes it via ``CloseOrphans``."""
        pool_net = sum((holding.net_base for holding in holdings), start=Decimal("0"))
        venue_net = await self._venue_net_position.net_position(pool, symbol)
        kind = classify_orphan(net, pool_net, venue_net)

        if kind is OrphanKind.REAL:
            own_holdings = [
                holding for holding in holdings if holding.strategy_id == strategy_id
            ]
            return GuardOutcome(proceed=False, real_orphan_holdings=own_holdings)

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
