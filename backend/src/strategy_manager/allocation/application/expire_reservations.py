"""``ExpireReservations``: TXN-C, the batch expiry sweep (design.md
§ Transaction Boundaries; spec: capital-allocation § Reservation Expiry).

**This changes no invariant.** ``sum_active`` already excludes reservations
past ``expires_at``, so a crashed worker's reservation stops blocking its pool
without any background process — that is a correctness property of the
availability read, not of this sweeper.

What the sweep buys is *bookkeeping and observability*: an orphaned reservation
that never reaches a terminal status is indistinguishable from one still being
worked on. Without it, a stalled worker looks exactly like a busy one, and the
row sits `PENDING` forever with nothing recording why.

Deliberately outside the advisory lock: the rows it touches are already
excluded from availability, so serializing the sweep behind the pool lock would
buy nothing and stall live allocations behind a maintenance batch.
"""

from dataclasses import dataclass

from strategy_manager.allocation.application.ports import CommitPort, ReservationSweepPort
from strategy_manager.shared.application.ports import ClockPort

DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class SweepResult:
    expired: int


class ExpireReservations:
    """Gives every reservation past its TTL a terminal status, in bounded
    batches so one sweep can never turn into an unbounded table rewrite."""

    def __init__(
        self,
        reservations: ReservationSweepPort,
        clock: ClockPort,
        commit: CommitPort,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._reservations = reservations
        self._clock = clock
        self._commit = commit
        self._batch_size = batch_size

    async def sweep(self) -> SweepResult:
        now = self._clock.now()
        expired = await self._reservations.expire_due(now, self._batch_size)
        await self._commit.commit()
        return SweepResult(expired=expired)
