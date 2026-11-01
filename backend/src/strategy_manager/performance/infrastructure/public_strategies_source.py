"""``SqlAlchemyPublicStrategiesSource``: the read that crosses users on purpose
(tasks.md F.4, decisions 27 and 30).

**No method takes a user.** That is the difference from every other read of this
module, and the reason each method names its columns: what is selected here is
all that can leave. ``raw_payload``, the secret's columns and the e-mail are not
in a statement at all.

**The list has one definition.** ``_LISTED`` is what makes a strategy public:
``PUBLIC``, not archived, and an author with a name. ``listings`` and ``listing``
both read through it, so a strategy off the list is not reachable by its id.

**One statement each**, ``ANY`` over the ids, whatever their number. Nothing here
locks or writes.

**A seat is live on ``users.mode``.** The brake is the use case's: it is one
value for everyone, so it never reaches a statement. A snapshot is joined on the
subscription's own pool and left-joined, because a pool with no balance read is
still someone trading live, and adds no money.

No ledger module is imported: a public figure comes from signals.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.performance.application.ports import PublicListing
from strategy_manager.performance.domain.public_capital import LiveSeat
from strategy_manager.performance.domain.public_record import RecordSignal
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.strategies.domain.strategy import Visibility
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

_LISTED = (
    StrategyRow.visibility == Visibility.PUBLIC.value,
    StrategyRow.archived_at.is_(None),
    UserRow.display_name.is_not(None),
)


def _listings_query() -> Select[Any]:
    return (
        select(
            StrategyRow.id,
            StrategyRow.name,
            UserRow.display_name,
            StrategyRow.exchange,
            StrategyRow.venue,
            StrategyRow.settlement_currency,
            StrategyRow.created_at,
        )
        .join(UserRow, UserRow.id == StrategyRow.author_id)
        .where(*_LISTED)
    )


def _listing(row: Row[Any]) -> PublicListing:
    return PublicListing(
        strategy_id=row.id,
        name=row.name,
        author_name=row.display_name,
        exchange=row.exchange,
        venue=row.venue,
        settlement_currency=row.settlement_currency,
        created_at=row.created_at,
    )


class SqlAlchemyPublicStrategiesSource:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def listings(self) -> Sequence[PublicListing]:
        """Oldest first, the id breaking a tie, so the order never depends on
        the order the rows arrive in."""
        rows = await self._session.execute(
            _listings_query().order_by(StrategyRow.created_at, StrategyRow.id)
        )
        return [_listing(row) for row in rows]

    async def listing(self, strategy_id: UUID) -> PublicListing | None:
        row = (
            await self._session.execute(_listings_query().where(StrategyRow.id == strategy_id))
        ).one_or_none()
        return None if row is None else _listing(row)

    async def signals(self, strategy_ids: Sequence[UUID]) -> Mapping[UUID, Sequence[RecordSignal]]:
        """Every stored signal of each strategy, whatever its status, by
        ``received_at`` and then ``id``: two signals of one instant read the same
        way on every request."""
        rows = await self._session.execute(
            select(
                SignalRow.strategy_id,
                SignalRow.symbol,
                SignalRow.received_at,
                SignalRow.position_size,
                SignalRow.price,
            )
            .where(SignalRow.strategy_id.in_(strategy_ids))
            .order_by(SignalRow.received_at, SignalRow.id)
        )
        found: defaultdict[UUID, list[RecordSignal]] = defaultdict(list)
        for row in rows:
            found[row.strategy_id].append(
                RecordSignal(row.symbol, row.received_at, row.position_size, row.price)
            )
        return found

    async def live_seats(self, strategy_ids: Sequence[UUID]) -> Mapping[UUID, Sequence[LiveSeat]]:
        rows = await self._session.execute(
            select(
                SubscriptionRow.strategy_id,
                SubscriptionRow.allocation_percent,
                PoolBalanceSnapshotRow.total,
            )
            .join(UserRow, UserRow.id == SubscriptionRow.user_id)
            .outerjoin(
                PoolBalanceSnapshotRow,
                PoolBalanceSnapshotRow.pool_id == SubscriptionRow.pool_id,
            )
            .where(
                SubscriptionRow.strategy_id.in_(strategy_ids),
                SubscriptionRow.status == SubscriptionStatus.ACTIVE.value,
                UserRow.mode == Mode.LIVE.value,
            )
        )
        found: defaultdict[UUID, list[LiveSeat]] = defaultdict(list)
        for row in rows:
            found[row.strategy_id].append(LiveSeat(row.allocation_percent, row.total))
        return found
