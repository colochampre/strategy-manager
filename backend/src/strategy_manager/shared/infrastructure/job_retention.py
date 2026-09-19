"""``PostgresJobRetention``: the one place that deletes from ``jobs``.

Implements ``JobRetentionPort`` — see ``purge_jobs.py`` for why only DONE rows
past the window go, and why FAILED never does.

The DELETE is driven by a subselect with a ``LIMIT`` rather than by the WHERE
clause alone, because ``DELETE ... LIMIT`` is not PostgreSQL syntax and the
bound is the whole point: without it this is the multi-million-row statement
the use case exists to avoid.

**No index supports this WHERE clause**, and that is deliberate.
``ix_jobs_claimable`` is PARTIAL on ``status = 'PENDING'``, so it cannot serve
a scan for DONE rows. At the steady state this system produces — roughly
10,000 rows a day against a 7-day window, so ~70,000 live rows — a once-daily
sequential scan is trivial, and an extra index would be paid for on every
enqueue, ack and fail instead. Revisit it if retention lengthens or job volume
grows by an order of magnitude; a partial index on ``(updated_at) WHERE status
= 'DONE'`` is the shape to add.
"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.infrastructure.models import JobRow

# The only status this adapter may ever remove. Named rather than inlined so
# the one-value list reads as a decision: FAILED is finished too, and is kept
# on purpose.
_PURGEABLE_STATUSES: tuple[str, ...] = ("DONE",)


class PostgresJobRetention:
    """Implements ``JobRetentionPort`` against the ``jobs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def delete_done_before(self, cutoff: datetime, limit: int) -> int:
        if limit <= 0:
            return 0

        doomed = (
            select(JobRow.id)
            .where(
                JobRow.status.in_(_PURGEABLE_STATUSES),
                JobRow.updated_at < cutoff,
            )
            .limit(limit)
        )
        result = cast(
            CursorResult[Any],
            await self._session.execute(delete(JobRow).where(JobRow.id.in_(doomed))),
        )
        return result.rowcount
