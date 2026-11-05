"""``SqlAlchemyPublicStrategiesSource``: the read that crosses users on purpose
(tasks.md F.4 and G.8, decisions 27, 30 and 34).

**No method takes a user.** That is the difference from every other read of this
module, and the reason each method names its columns: what is selected here is
all that can leave. ``raw_payload``, the secret's columns and the e-mail are not
in a statement at all.

**The list has one definition.** ``LISTED`` is what makes a strategy public:
``PUBLIC``, not archived, and an author with a name. ``listings`` and ``listing``
both read through it, so a strategy off the list is not reachable by its id. The
open-positions read links to the public page through it too, so a link cannot lead
to a page that answers 404.

**One statement each**, ``ANY`` over the ids, whatever their number. Nothing here
locks or writes.

**A seat is live on ``users.mode`` and a key that can trade on the market.** A seat
with neither opens nothing. The brake is the use case's: it is one value for
everyone, so it never reaches a statement. A snapshot is joined on the
subscription's own pool and left-joined, because a pool with no balance read is
still someone trading live, and adds no money.

**The record reads the author's real fills** (decision 34): ledger rows whose
user is the strategy's author and whose fill id does not carry the rehearsal
prefix, the same mark ``SqlAlchemyAllocationFillsSource`` sorts by. Only their
sums leave, and only as far as the record, which turns them into a ratio: no
amount reaches a public body. No signal is read, so an alert's price cannot
build a record.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    has_trade_capable_key,
)
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.application.ports import PublicListing
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.public_capital import LiveSeat
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.strategies.domain.strategy import Visibility
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

LISTED = (
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
        .where(*LISTED)
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

    async def author_fills(
        self, strategy_ids: Sequence[UUID]
    ) -> Mapping[UUID, Sequence[FillGroup]]:
        """Each strategy's real fills by its author, folded per allocation, side,
        fee currency and spelling as ``SqlAlchemyAllocationFillsSource`` folds
        them, so ``derive_trades`` reads both the same way."""
        is_rehearsal = LedgerEntryRow.exchange_fill_id.startswith(
            REHEARSAL_FILL_ID_PREFIX, autoescape=True
        )
        keys = (
            LedgerEntryRow.allocation_id,
            LedgerEntryRow.strategy_id,
            LedgerEntryRow.exchange,
            LedgerEntryRow.venue,
            LedgerEntryRow.settlement_currency,
            LedgerEntryRow.side,
            LedgerEntryRow.fee_currency,
            LedgerEntryRow.symbol,
        )
        rows = await self._session.execute(
            select(
                *keys,
                func.sum(LedgerEntryRow.quantity).label("quantity"),
                func.sum(LedgerEntryRow.notional).label("notional"),
                func.sum(LedgerEntryRow.fee).label("fee"),
                func.min(LedgerEntryRow.filled_at).label("first_filled_at"),
                func.max(LedgerEntryRow.filled_at).label("last_filled_at"),
            )
            .join(StrategyRow, StrategyRow.id == LedgerEntryRow.strategy_id)
            .where(
                LedgerEntryRow.strategy_id.in_(strategy_ids),
                LedgerEntryRow.user_id == StrategyRow.author_id,
                ~is_rehearsal,
            )
            .group_by(*keys)
            .order_by(*keys)
        )
        found: defaultdict[UUID, list[FillGroup]] = defaultdict(list)
        for row in rows:
            found[row.strategy_id].append(
                FillGroup(
                    allocation_id=row.allocation_id,
                    strategy_id=row.strategy_id,
                    exchange=row.exchange,
                    venue=row.venue,
                    settlement_currency=row.settlement_currency,
                    symbol=row.symbol,
                    side=row.side,
                    fee_currency=row.fee_currency,
                    quantity=Decimal(row.quantity),
                    notional=Decimal(row.notional),
                    fee=Decimal(row.fee),
                    first_filled_at=row.first_filled_at,
                    last_filled_at=row.last_filled_at,
                    # No public figure divides by a pool: the record is a price move.
                    pool_total_at_open=None,
                    rehearsal=False,
                )
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
            .join(StrategyRow, StrategyRow.id == SubscriptionRow.strategy_id)
            .outerjoin(
                PoolBalanceSnapshotRow,
                PoolBalanceSnapshotRow.pool_id == SubscriptionRow.pool_id,
            )
            .where(
                SubscriptionRow.strategy_id.in_(strategy_ids),
                SubscriptionRow.status == SubscriptionStatus.ACTIVE.value,
                UserRow.mode == Mode.LIVE.value,
                has_trade_capable_key(SubscriptionRow.user_id, StrategyRow.exchange),
            )
        )
        found: defaultdict[UUID, list[LiveSeat]] = defaultdict(list)
        for row in rows:
            found[row.strategy_id].append(LiveSeat(row.allocation_percent, row.total))
        return found
