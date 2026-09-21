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
   nothing is in flight to explain it) -- refuse with a WARNING. Until S4
   classifies it, nothing about WHY it diverges is known (owner decision A1:
   "a divergent holding is REFUSED with nothing classified").

A refusal here MUST NEVER reach ``AllocateCapital.allocate()`` -- the caller
is expected to check ``GuardOutcome.proceed`` before doing anything else.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.signals.application.ports import InFlightWorkPort, PoolKey, SymbolHoldingsPort
from strategy_manager.signals.domain.holding import HeldAllocation, strategy_net

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
        clock: ClockPort,
        delayed_open_max_signal_age_seconds: float,
    ) -> None:
        self._holdings = holdings
        self._in_flight_work = in_flight_work
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

        return self._refuse_divergent(pool, strategy_id, symbol, holdings, net)

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

    def _refuse_divergent(
        self,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        net: Decimal,
    ) -> GuardOutcome:
        own_allocations = ", ".join(
            f"{holding.allocation_id}={holding.net_base}"
            for holding in holdings
            if holding.strategy_id == strategy_id
        )
        refused = (
            f"strategy {strategy_id} holds a divergent net {net} on {symbol} in "
            f"pool {pool} (allocations: {own_allocations}); refusing until it is "
            "classified"
        )
        logger.warning("refusing divergent holding: %s", refused)
        return GuardOutcome(proceed=False, refused=refused)
