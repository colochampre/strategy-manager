"""``SqlAlchemyUsersSource``: implements ``UsersSourcePort`` over the readers each
fact already has, so the list cannot drift from them. ``read_key_coverage`` is the
worker's own degraded sweep, and ``open_allocations`` is the mode guard's and the
open-positions panel's one definition of "open".
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.key_coverage import read_key_coverage
from strategy_manager.admin.application.ports import ExchangeCoverage
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)


class SqlAlchemyUsersSource:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def users(self) -> Sequence[User]:
        return await SqlAlchemyUserRepository(self._session).everyone()

    async def coverage(self) -> ExchangeCoverage:
        coverage = await read_key_coverage(self._session)
        return ExchangeCoverage(enabled_pools=coverage.configured, active_keys=coverage.active)

    async def live_subscriptions(self) -> Mapping[UUID, int]:
        return await SqlAlchemySubscriptionRepository(self._session).live_counts_by_user()

    async def open_allocation_owners(self) -> Sequence[UUID]:
        allocations = await SqlAlchemyModeOriginReader(self._session).open_allocations()
        return [allocation.user_id for allocation in allocations]
