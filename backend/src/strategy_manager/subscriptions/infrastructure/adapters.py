"""Adapters of the ports ``subscriptions.application`` declares.

Each reads another module's table through its own repository or row, the way
``strategies.infrastructure.exposure_adapter`` does: the consumer declares the
port, the infrastructure composes the providers.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.allocation.domain.reservation import ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.application.ports import Market, StrategyMarket

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
        )


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


class OpenAllocationAdapter:
    """Implements ``OpenAllocationPort``, scoped to one user.

    The same question ``StrategyExposureAdapter`` asks for an archive, asked for
    one user instead of every user: the ledger's open allocations of the
    strategy (per allocation, never netted across them, under every spelling of
    the symbol), and a reservation of that user's still holding capital."""

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
        raw_symbols = await self._ledger.distinct_symbols_for_strategy(
            exchange, venue, currency, strategy_id
        )
        for symbol in sorted({market_key(raw) for raw in raw_symbols}):
            held = await self._holdings.symbol_holdings(user_id, market, symbol)
            if any(allocation.strategy_id == strategy_id for allocation in held):
                return True

        reserved = (
            await self._session.execute(
                select(ReservationRow.id)
                .where(
                    ReservationRow.user_id == user_id,
                    ReservationRow.strategy_id == strategy_id,
                    ReservationRow.exchange == exchange,
                    ReservationRow.venue == venue,
                    ReservationRow.settlement_currency == currency,
                    ReservationRow.status.in_(_LIVE_RESERVATION),
                    ReservationRow.terminal_at.is_(None),
                )
                .limit(1)
            )
        ).first()
        return reserved is not None
