"""Startup guard: ``DRY_RUN`` must match the origin of what the ledger holds
(owner decision 28).

Flipping ``DRY_RUN`` with a position still open sends its close to the wrong
exchange. Rehearsal state closed against a live venue finds nothing; live state
closed against the fake exchange is booked flat while the real position stays
open at the venue. The same goes for an order still waiting for
``execution.settle``: it has no fills yet, so the open-allocation read cannot
see it, but its settle would ask the other exchange and could release a
reservation for an order that really filled.

Refusing to start is deliberate, and unlike decision 20's degraded start: the
flip is a manual act done with a restart, the owner is there to read the ERROR,
and a degraded worker would have to guard every signal instead.

The refusal is a ``StartupRefused`` (decision 29) raised out of the worker's
startup. It is logged at ERROR FIRST, because an exception is not a log record
and only a log record reaches the alert bridge, and it says so (``logged``) so
the worker does not write a second one; ``worker.main`` then exits 78. This
use case may raise the startup type directly because nothing but the worker's
startup calls it.
"""

import logging

from strategy_manager.execution.application.ports import ModeOriginReaderPort
from strategy_manager.execution.domain.mode_origin import describe_refusal, find_mismatches
from strategy_manager.shared.domain.startup_refusal import StartupRefused

logger = logging.getLogger(__name__)


async def assert_mode_matches_ledger(*, dry_run: bool, reader: ModeOriginReaderPort) -> None:
    mismatches = find_mismatches(
        dry_run=dry_run,
        open_allocations=await reader.open_allocations(),
        in_flight=await reader.in_flight_attempts(),
    )
    if not mismatches:
        return

    logger.error("%s", describe_refusal(dry_run=dry_run, mismatches=mismatches))
    raise StartupRefused(
        f"DRY_RUN is {'true' if dry_run else 'false'} but {len(mismatches)} open "
        "position(s) or in-flight order(s) in the ledger belong to the other "
        "mode. Refusing to start; the ERROR logged just above names each one "
        "and the way out.",
        logged=True,
    )
