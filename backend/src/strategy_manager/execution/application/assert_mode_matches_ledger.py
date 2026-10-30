"""Startup guard: what the ledger holds must agree with the mode its reservation
recorded, and a real position must have a key that can close it (owner decision
28, multi-user design AD7).

A close and a settle follow the recorded mode, so a record that disagrees sends
them to the wrong exchange. Rehearsal state closed against a live venue finds
nothing; live state closed against the fake exchange is booked flat while the
real position stays open at the venue. The same goes for an order still waiting
for ``execution.settle``: it has no fills yet, so the open-allocation read
cannot see it, but its settle would ask the other exchange and could release a
reservation for an order that really filled.

``DRY_RUN`` has no say here. A real position closes for real under the brake
(decision 14), so that combination is valid. What it needs is a key, and a user
whose key is gone cannot close: the guard names them.

Refusing to start is deliberate, and unlike decision 20's degraded start: a
worker that starts would close into the wrong side or fail every close, the
owner is there to read the ERROR, and a degraded worker would have to guard
every signal instead.

The refusal is a ``StartupRefused`` (decision 29) raised out of the worker's
startup. It is logged at ERROR FIRST, because an exception is not a log record
and only a log record reaches the alert bridge, and it says so (``logged``) so
the worker does not write a second one; ``worker.main`` then exits 78. This
use case may raise the startup type directly because nothing but the worker's
startup calls it.
"""

import logging

from strategy_manager.execution.application.ports import (
    ModeOriginReaderPort,
    TradeCapableKeysPort,
)
from strategy_manager.execution.domain.mode_origin import (
    describe_refusal,
    find_mismatches,
    find_unclosable,
)
from strategy_manager.shared.domain.startup_refusal import StartupRefused

logger = logging.getLogger(__name__)


async def assert_mode_matches_ledger(
    *, reader: ModeOriginReaderPort, keys: TradeCapableKeysPort
) -> None:
    open_allocations = await reader.open_allocations()
    mismatches = find_mismatches(
        open_allocations=open_allocations,
        in_flight=await reader.in_flight_attempts(),
    )
    unclosable = find_unclosable(
        open_allocations=open_allocations,
        trade_capable=await keys.trade_capable_keys(),
    )
    if not mismatches and not unclosable:
        return

    logger.error("%s", describe_refusal(mismatches=mismatches, unclosable=unclosable))
    raise StartupRefused(
        f"{len(mismatches)} open position(s) or in-flight order(s) disagree with the "
        f"mode their reservation recorded, and {len(unclosable)} user(s) hold real "
        "positions no key of theirs can close. Refusing to start; the ERROR logged "
        "just above names each one and the way out.",
        logged=True,
    )
