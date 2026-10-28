"""The real ``StrategySubscribersAdapter`` on a session, for the integration tests
that build ``ArchiveStrategy`` and ``DeleteStrategy`` by hand."""

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)


def real_subscribers(session: AsyncSession) -> StrategySubscribersAdapter:
    ledger = SqlAlchemyLedgerRepository(session)
    return StrategySubscribersAdapter(session, ledger, ReadSymbolHoldings(ledger))
