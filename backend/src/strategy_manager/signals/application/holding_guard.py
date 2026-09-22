"""``HoldingGuard``: the Existing-Position Guard (spec: capital-allocation §
Existing-Position Guard) run at the top of ``_handle_consumes``, before any
capital is allocated (design.md § "Guard order").

**Precedence, in order:**

1. The signal already owns a reservation (a retry past the point
   ``AllocateCapital`` ran) -- resume, skip every other check.
2. The strategy has execution work in flight on this symbol -- raise
   ``HoldingNotSettledYet`` so the job retries, UNLESS the signal is already
   older than ``delayed_open_max_signal_age_seconds``, in which case give up
   and refuse with a WARNING instead of retrying forever.
3. The strategy's ledger net on the symbol is zero -- proceed.
4. Otherwise the holding is divergent (ledger and venue may disagree, but
   nothing is in flight to explain it) -- read the venue's own net (the
   ONE remote call this guard makes, before the pool's advisory lock is ever
   touched) and classify it (spec: capital-allocation § Orphan
   Classification; design.md § S4). REAL, GHOST and AMBIGUOUS all refuse
   with a WARNING today -- owner decision A1 keeps REAL refused until S6
   delivers closing it, and A2 refuses AMBIGUOUS exactly like a ghost.

A refusal here MUST NEVER reach ``AllocateCapital.allocate()`` -- the caller
is expected to check ``GuardOutcome.proceed`` before doing anything else.
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


class HoldingNotSettledYet(Exception):
    """The strategy has execution work in flight on this symbol, so its
    ledger holding cannot be trusted yet.

    Deliberately not a ``DomainError``: like ``NothingRecordedYet``
    (``execution.application.close_position``), this is a scheduling
    condition, not a business outcome, and the queue's own backoff is what
    should retry it -- not this use case.
    """


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    """``proceed`` True means the caller may continue toward
    ``AllocateCapital``; ``False`` means it must not, and ``refused`` names
    why (mirrors ``ProcessSignalResult.refused``)."""

    proceed: bool
    refused: str | None = None


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
            return self._on_in_flight(pool, strategy_id, symbol, now, received_at)

        holdings = await self._holdings.symbol_holdings(pool, symbol)
        net = strategy_net(holdings, strategy_id)
        if net == 0:
            return GuardOutcome(proceed=True)

        return await self._classify_and_refuse(pool, strategy_id, symbol, holdings, net)

    def _on_in_flight(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        now: datetime,
        received_at: datetime,
    ) -> GuardOutcome:
        age_seconds = (now - received_at).total_seconds()
        if age_seconds <= self._delayed_open_max_signal_age_seconds:
            raise HoldingNotSettledYet(
                f"strategy {strategy_id} has work in flight on {symbol} in pool "
                f"{pool}; the opening signal will retry once it settles"
            )

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
