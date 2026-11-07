"""Adapters of the ports ``subscriptions.application`` declares.

Each reads another module's table through its own repository or row, the way
``strategies.infrastructure.exposure_adapter`` does: the consumer declares the
port, the infrastructure composes the providers.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.allocation.domain.reservation import ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.domain.invite_code import DeadCode, InviteCode, IssuedCode
from strategy_manager.strategies.domain.strategy import Visibility
from strategy_manager.strategies.infrastructure.author_names import SqlAlchemyAuthorNames
from strategy_manager.strategies.infrastructure.invite_codes_adapter import live_at
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.application.ports import (
    LeavingSubscription,
    Market,
    StrategyMarket,
)
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import InviteCodeRow, SubscriptionRow

_LIVE_RESERVATION = (ReservationStatus.PENDING.value, ReservationStatus.SUBMITTED.value)


class SqlAlchemyStrategyLookup:
    """Implements ``StrategyLookupPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, strategy_id: UUID) -> StrategyMarket | None:
        row = await self._session.get(StrategyRow, strategy_id)
        if row is None:
            return None
        return StrategyMarket(
            id=row.id,
            market=(row.exchange, row.venue, row.settlement_currency),
            archived=row.archived_at is not None,
            author_id=row.author_id,
            visibility=Visibility(row.visibility),
            author_named=await SqlAlchemyAuthorNames(self._session).has_display_name(
                row.author_id
            ),
            share_token=row.share_token,
        )


class SqlAlchemyInviteCodeSpend:
    """Implements ``InviteCodeSpendPort`` in the request's own session: the seat and
    its code commit together or not at all."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def spend(
        self,
        strategy_id: UUID,
        code: InviteCode,
        user_id: UUID,
        subscription_id: UUID,
        now: datetime,
    ) -> DeadCode | None:
        # One statement: the UPDATE waits on the row's lock and re-reads it, so a
        # code spent or revoked by another transaction meanwhile matches nothing.
        spent = (
            await self._session.execute(
                update(InviteCodeRow)
                .where(
                    InviteCodeRow.strategy_id == strategy_id,
                    InviteCodeRow.code_hash == code.hash,
                    live_at(now),
                )
                .values(redeemed_by=user_id, redeemed_at=now, subscription_id=subscription_id)
                .returning(InviteCodeRow.id)
            )
        ).scalar_one_or_none()
        if spent is not None:
            return None
        row = (
            await self._session.execute(
                select(
                    InviteCodeRow.expires_at, InviteCodeRow.revoked_at, InviteCodeRow.redeemed_at
                ).where(
                    InviteCodeRow.strategy_id == strategy_id, InviteCodeRow.code_hash == code.hash
                )
            )
        ).one_or_none()
        if row is None:
            # Gone with its strategy: it opens nothing, as a revoked one.
            return DeadCode.REVOKED
        issued = IssuedCode(
            expires_at=row.expires_at, revoked_at=row.revoked_at, redeemed_at=row.redeemed_at
        )
        reason = issued.why_dead(now)
        if reason is None:
            # The UPDATE matched nothing at this same instant, so the row cannot read
            # live here; if it does, the two disagree and nothing is written.
            raise RuntimeError(f"invite code of strategy {strategy_id} read live but not spent")
        return reason


class SqlAlchemyUserPools:
    """Implements ``UserPoolPort``: the pool of THIS user, never another's."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pool_id(self, user_id: UUID, market: Market) -> int | None:
        exchange, venue, currency = market
        found = (
            await self._session.execute(
                select(CapitalPoolRow.id).where(
                    CapitalPoolRow.user_id == user_id,
                    CapitalPoolRow.exchange == exchange,
                    CapitalPoolRow.venue == venue,
                    CapitalPoolRow.settlement_currency == currency,
                )
            )
        ).scalar_one_or_none()
        return None if found is None else int(found)


class SqlAlchemyEnabledUserPools:
    """Implements ``UserPoolPort`` for a new subscription: only a pool with a key
    behind it. Deleting a key disables its pool and keeps the row, so a row says
    nothing about a key (decision 13). Registering a strategy keeps
    ``SqlAlchemyUserPools``, which has its own check of the pool."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pool_id(self, user_id: UUID, market: Market) -> int | None:
        exchange, venue, currency = market
        found = (
            await self._session.execute(
                select(CapitalPoolRow.id).where(
                    CapitalPoolRow.user_id == user_id,
                    CapitalPoolRow.exchange == exchange,
                    CapitalPoolRow.venue == venue,
                    CapitalPoolRow.settlement_currency == currency,
                    CapitalPoolRow.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        return None if found is None else int(found)


class SqlAlchemyLeavingSubscriptions:
    """Implements ``LeavingSubscriptionsPort``.

    **Global by design, whoever's the subscription** (multi-user design AD8): the
    worker's own housekeeping, with no user context on its path. Here and not in the
    repository, whose reads are scoped to a user, because it joins the strategy for the
    market the pool lock is keyed by."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def leaving(self) -> list[LeavingSubscription]:
        result = await self._session.execute(
            select(
                SubscriptionRow.user_id,
                SubscriptionRow.strategy_id,
                StrategyRow.exchange,
                StrategyRow.venue,
                StrategyRow.settlement_currency,
            )
            .join(StrategyRow, StrategyRow.id == SubscriptionRow.strategy_id)
            .where(SubscriptionRow.status == SubscriptionStatus.LEAVING.value)
            .order_by(SubscriptionRow.left_at, SubscriptionRow.id)
        )
        return [
            LeavingSubscription(user_id, strategy_id, (exchange, venue, currency))
            for user_id, strategy_id, exchange, venue, currency in result.all()
        ]


class OpenAllocationAdapter:
    """Implements ``OpenAllocationPort``, scoped to one user.

    The same question ``StrategyExposureAdapter`` asks for an archive, asked for
    one user instead of every user: a reservation of that user's still holding
    capital, an opening order of theirs still in flight, and the ledger's open
    allocations of the strategy (per allocation, never netted across them, under
    every spelling of the symbol).

    **An order in flight counts by its attempt, not its reservation.** The sweeper
    expires a SUBMITTED reservation at its TTL, and the order may still fill. A close
    reaches ACTIVE and LEAVING subscribers only, so a subscription ended on that
    reading leaves a position no close reaches. A closing order needs no such read: it
    unwinds what the ledger still holds.

    **The order of the reads is part of the check**, as in
    ``SqlAlchemyLiveExposure``: exposure moves from the reservation to the attempt to
    the ledger, and an opening's settle takes no pool lock. Read this way, whatever
    left one read has already reached the next."""

    def __init__(
        self,
        session: AsyncSession,
        ledger: SqlAlchemyLedgerRepository,
        holdings: ReadSymbolHoldings,
    ) -> None:
        self._session = session
        self._ledger = ledger
        self._holdings = holdings

    async def holds_open_allocation(
        self, user_id: UUID, strategy_id: UUID, market: Market
    ) -> bool:
        exchange, venue, currency = market
        of_this_strategy = (
            ReservationRow.user_id == user_id,
            ReservationRow.strategy_id == strategy_id,
            ReservationRow.exchange == exchange,
            ReservationRow.venue == venue,
            ReservationRow.settlement_currency == currency,
        )

        reserved = (
            await self._session.execute(
                select(ReservationRow.id)
                .where(
                    *of_this_strategy,
                    ReservationRow.status.in_(_LIVE_RESERVATION),
                    ReservationRow.terminal_at.is_(None),
                )
                .limit(1)
            )
        ).first()
        if reserved is not None:
            return True

        in_flight = (
            await self._session.execute(
                select(ExecutionAttemptRow.id)
                .join(ReservationRow, ReservationRow.id == ExecutionAttemptRow.reservation_id)
                .where(
                    *of_this_strategy,
                    ExecutionAttemptRow.status == ExecutionStatus.SUBMITTED.value,
                )
                .limit(1)
            )
        ).first()
        if in_flight is not None:
            return True

        raw_symbols = await self._ledger.distinct_symbols_for_strategy(
            exchange, venue, currency, strategy_id
        )
        for symbol in sorted({market_key(raw) for raw in raw_symbols}):
            held = await self._holdings.symbol_holdings(user_id, market, symbol)
            if any(allocation.strategy_id == strategy_id for allocation in held):
                return True
        return False
