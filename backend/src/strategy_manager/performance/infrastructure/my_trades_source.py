"""``SqlAlchemyMyTradesSource``: the three reads behind ``GET /performance/trades``.

Each is ONE statement however many ids it is asked about, and each filters on
``user_id`` (multi-user design AD8).

* ``pools_with_fills``: ``SELECT DISTINCT`` of the pool columns of the user's
  OWN ledger rows. It does not read ``capital_pools``: a pool whose row was
  removed, or switched off, still holds fills, and the list must not miss it.
* ``strategy_facts``: name, archive flag and which page of the strategy the user
  can open (as the open positions compute it, ``strategy_page_of``).
* ``close_event_kinds``: the kind of each allocation's close safety event. It
  reads the ``safety_events`` table directly, as the neighbouring adapters read
  other modules' tables; the safety module's application code is not imported.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.application.ports import TradeStrategyFacts
from strategy_manager.performance.domain.close_cause import CLOSE_EVENT_KINDS
from strategy_manager.performance.domain.open_position import strategy_page_of
from strategy_manager.performance.infrastructure.public_strategies_source import LINKED
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemyMyTradesSource:
    """Implements ``MyTradesSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pools_with_fills(self, user_id: UUID) -> Sequence[PoolKey]:
        rows = await self._session.execute(
            select(
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
            )
            .where(LedgerEntryRow.user_id == user_id)
            .distinct()
            .order_by(
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
            )
        )
        return [PoolKey(Exchange(r[0]), Venue(r[1]), Currency(r[2])) for r in rows.all()]

    async def strategy_facts(
        self, user_id: UUID, strategy_ids: Sequence[UUID]
    ) -> Mapping[UUID, TradeStrategyFacts]:
        if not strategy_ids:
            return {}
        rows = await self._session.execute(
            select(
                StrategyRow.id,
                StrategyRow.name,
                StrategyRow.archived_at.is_not(None),
                StrategyRow.author_id == user_id,
                and_(*LINKED),
            )
            .outerjoin(UserRow, UserRow.id == StrategyRow.author_id)
            .where(StrategyRow.id.in_(strategy_ids))
        )
        return {
            row[0]: TradeStrategyFacts(
                strategy_id=row[0],
                name=row[1],
                archived=bool(row[2]),
                page=strategy_page_of(authored=bool(row[3]), listed=bool(row[4])),
            )
            for row in rows.all()
        }

    async def close_event_kinds(
        self, user_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, str]:
        if not allocation_ids:
            return {}
        rows = await self._session.execute(
            select(SafetyEventRow.allocation_id, SafetyEventRow.kind)
            .where(
                SafetyEventRow.user_id == user_id,
                SafetyEventRow.allocation_id.in_(allocation_ids),
                SafetyEventRow.kind.in_(CLOSE_EVENT_KINDS),
            )
            .order_by(SafetyEventRow.occurred_at, SafetyEventRow.id)
        )
        # Oldest first, so the latest event of an allocation is the one kept.
        return {row[0]: row[1] for row in rows.all()}
