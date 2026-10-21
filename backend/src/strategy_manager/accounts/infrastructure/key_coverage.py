"""Which exchanges have an enabled pool, and which hold an active key, read
together.

The worker's DEGRADED check compares the two. Deleting a key from the panel
turns both off in one commit, and saving one turns both on, so the two sets
must describe the same moment: read apart, a commit landing between the reads
shows an enabled pool with no key, and a false ERROR reaches Telegram (seen
2026-10-21, when the check took its pools from the worker's in-memory set,
which only catches up on the next balance.sync reload). One statement is one
snapshot under READ COMMITTED, so both come from a single SELECT.
"""

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow, ExchangeCredentialRow


@dataclass(frozen=True)
class KeyCoverage:
    configured: frozenset[str]
    active: frozenset[str]


async def read_key_coverage(session: AsyncSession) -> KeyCoverage:
    configured = (
        select(func.array_agg(distinct(CapitalPoolRow.exchange)))
        .where(CapitalPoolRow.enabled.is_(True))
        .scalar_subquery()
    )
    active = (
        select(func.array_agg(distinct(ExchangeCredentialRow.exchange)))
        .where(ExchangeCredentialRow.is_active.is_(True))
        .scalar_subquery()
    )
    row = (await session.execute(select(configured, active))).one()
    # ``array_agg`` over no rows is NULL, not an empty array.
    return KeyCoverage(configured=frozenset(row[0] or ()), active=frozenset(row[1] or ()))
