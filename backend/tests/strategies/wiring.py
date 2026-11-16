"""The real ``StrategySubscribersAdapter`` on a session, for the integration tests
that build ``ArchiveStrategy`` and ``DeleteStrategy`` by hand."""

from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)


class RealDisableGuard(TypedDict):
    """The keyword arguments ``UpdateStrategy`` takes for the disable guard, real."""

    pool_lock: PoolLockAdapter
    subscribers: StrategySubscribersAdapter
    exposure: StrategyExposureAdapter


def real_disable_guard(session: AsyncSession) -> RealDisableGuard:
    ledger = SqlAlchemyLedgerRepository(session)
    return {
        "pool_lock": PoolLockAdapter(session),
        "subscribers": real_subscribers(session),
        "exposure": StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
    }


def real_subscribers(session: AsyncSession) -> StrategySubscribersAdapter:
    ledger = SqlAlchemyLedgerRepository(session)
    return StrategySubscribersAdapter(session, ledger, ReadSymbolHoldings(ledger))
