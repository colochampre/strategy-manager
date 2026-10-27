"""Which ``(user, exchange)`` pairs have an enabled pool, and which hold an
active key, read together (multi-user design AD9).

The worker's DEGRADED check compares the two. Deleting a key from the panel
turns both off in one commit, and saving one turns both on, so the two sets
must describe the same moment: read apart, a commit landing between the reads
shows an enabled pool with no key, and a false ERROR reaches Telegram (seen
2026-10-21, when the check took its pools from the worker's in-memory set,
which only catches up on the next balance.sync reload). One statement is one
snapshot under READ COMMITTED, so both come from a single SELECT: a
``UNION ALL`` of the two, each row tagged with the set it belongs to.

A pair, never an exchange alone: one user's key on an exchange does not cover
another user's pool on it, and one user's missing key degrades only that user.
This is the worker's global sweep across users, by design: it reads no secret,
and every consumer acts on each pair separately.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow, ExchangeCredentialRow

UserExchange = tuple[UUID, str]
"""``(user_id, exchange)``: one user's account on one exchange."""

_POOL = "pool"
_KEY = "key"


@dataclass(frozen=True)
class KeyCoverage:
    configured: frozenset[UserExchange]
    active: frozenset[UserExchange]


async def read_key_coverage(session: AsyncSession) -> KeyCoverage:
    pools = select(
        literal(_POOL).label("kind"), CapitalPoolRow.user_id, CapitalPoolRow.exchange
    ).where(CapitalPoolRow.enabled.is_(True))
    keys = select(
        literal(_KEY).label("kind"), ExchangeCredentialRow.user_id, ExchangeCredentialRow.exchange
    ).where(ExchangeCredentialRow.is_active.is_(True))
    rows = (await session.execute(union_all(pools, keys))).all()
    return KeyCoverage(
        configured=frozenset((row.user_id, row.exchange) for row in rows if row.kind == _POOL),
        active=frozenset((row.user_id, row.exchange) for row in rows if row.kind == _KEY),
    )
