"""The adapters ``DeleteAccount`` works through (account-deletion S3).

Each one writes and flushes, and none commits: the use case commits once, which
is also what releases the pool locks. The strategy's own pieces are reused --
the exposure ``ArchiveStrategy`` refuses on, the subscribers' pools it locks, the
seats it ends -- so a deletion and an archive cannot disagree on what is held.
"""

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow, ExchangeCredentialRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.identity.application.ports import AuthoredStrategy, LockedPool
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.domain.strategy import Strategy, Visibility
from strategy_manager.strategies.domain.webhook_secret import (
    hash_webhook_secret,
    new_webhook_secret,
    webhook_secret_last4,
)
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.repository import AuthorStrategyRepository
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

_LIVE = (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.LEAVING.value)


class SqlAlchemyAccountPools:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pools(self, user_id: UUID) -> list[LockedPool]:
        result = await self._session.execute(
            select(
                CapitalPoolRow.id,
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
            )
            .where(CapitalPoolRow.user_id == user_id)
            .order_by(CapitalPoolRow.id)
        )
        return [
            LockedPool(
                pool_id=int(pool_id),
                user_id=user_id,
                exchange=exchange,
                venue=venue,
                currency=currency,
            )
            for pool_id, exchange, venue, currency in result.all()
        ]

    async def disable_all(self, user_id: UUID) -> int:
        result = await self._session.execute(
            update(CapitalPoolRow)
            .where(CapitalPoolRow.user_id == user_id, CapitalPoolRow.enabled.is_(True))
            .values(enabled=False)
            .returning(CapitalPoolRow.id)
        )
        return len(result.all())


class SqlAlchemyAuthoredStrategies:
    """The strategies ``author_id`` authors, and nobody else's: every read is
    scoped to that author, so a strategy id from anywhere else matches nothing."""

    def __init__(self, session: AsyncSession, author_id: UUID) -> None:
        self._session = session
        self._author_id = author_id
        self._strategies = AuthorStrategyRepository(session, author_id)
        ledger = SqlAlchemyLedgerRepository(session)
        self._subscribers = StrategySubscribersAdapter(session, ledger, ReadSymbolHoldings(ledger))
        self._exposure = StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        )
        self._enablement = SqlAlchemyEnablementLog(session)

    async def authored(self, user_id: UUID) -> list[AuthoredStrategy]:
        if user_id != self._author_id:
            return []
        strategies = await self._strategies.list_all(include_archived=True)
        return [
            AuthoredStrategy(id=s.id, name=s.name) for s in sorted(strategies, key=lambda s: s.id)
        ]

    async def subscriber_pools(self, strategy_id: UUID) -> list[LockedPool]:
        return [
            LockedPool(
                pool_id=pool.pool_id,
                user_id=pool.user_id,
                exchange=pool.pool[0],
                venue=pool.pool[1],
                currency=pool.pool[2],
            )
            for pool in await self._subscribers.live_pools(strategy_id)
        ]

    async def lock(self, strategy_id: UUID) -> None:
        await self._strategies.get_by_id_for_update(strategy_id)

    async def exposure(self, strategy_id: UUID) -> tuple[str, ...] | None:
        strategy = await self._own(strategy_id)
        held = await self._exposure.exposure(strategy.id, _pool(strategy))
        return None if held.is_empty() else tuple(sorted(held.symbols))

    async def close(self, strategy_id: UUID, now: datetime) -> int:
        strategy = await self._own(strategy_id)
        # A secret nobody holds: its plain value is dropped here, so the author's
        # TradingView alerts are refused from now on.
        secret = new_webhook_secret()
        await self._strategies.replace_webhook_secret(
            strategy.id, hash_webhook_secret(secret), webhook_secret_last4(secret)
        )
        await self._strategies.update(
            replace(
                strategy,
                visibility=Visibility.PRIVATE,
                share_token=None,
                enabled=False,
                archived_at=strategy.archived_at or now,
            )
        )
        if strategy.enabled:
            await self._enablement.append(strategy.id, False, now)
        return await self._subscribers.end_all(strategy.id, now)

    async def _own(self, strategy_id: UUID) -> Strategy:
        strategy = await self._strategies.get_by_id(strategy_id)
        if strategy is None:
            raise LookupError(f"strategy {strategy_id} is not authored by {self._author_id}")
        return strategy


class SqlAlchemyOwnSeats:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def end_live(self, user_id: UUID, now: datetime) -> int:
        result = await self._session.execute(
            update(SubscriptionRow)
            .where(SubscriptionRow.user_id == user_id, SubscriptionRow.status.in_(_LIVE))
            .values(status=SubscriptionStatus.ENDED.value, ended_at=now)
            .returning(SubscriptionRow.id)
            .execution_options(synchronize_session="fetch")
        )
        return len(result.all())


class SqlAlchemyAccountCredentials:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def delete_all(self, user_id: UUID) -> int:
        """Every row, active or not, ciphertext included: deactivating keeps the
        sealed columns (``DeleteCredential``), which a deleted account must not."""
        result = await self._session.execute(
            delete(ExchangeCredentialRow)
            .where(ExchangeCredentialRow.user_id == user_id)
            .returning(ExchangeCredentialRow.id)
        )
        return len(result.all())


def _pool(strategy: Strategy) -> tuple[str, str, str]:
    return (
        strategy.policy.exchange.value,
        strategy.policy.venue.value,
        strategy.policy.settlement_currency.value,
    )
