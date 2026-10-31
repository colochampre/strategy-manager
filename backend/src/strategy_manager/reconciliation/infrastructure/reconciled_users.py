"""``SqlAlchemyReconciledUsers``: whose account the venue is compared with
(multi-user design AD7, tasks.md E.6).

Reconciliation asks whether the ledger's real fills match a real account, so a
user in simulation with nothing real has nothing to compare. A user is reconciled
while any of these holds:

- their mode is ``LIVE``;
- they hold something real (``SqlAlchemyLiveExposure``): a user back in simulation
  under the brake, or one whose flip landed after an opening, still has a position
  on the venue;
- they have a discrepancy still open. A venue position the ledger reads as flat is
  something real the exposure read cannot see, and only another scan can resolve
  it, so scanning stops once it is clean rather than the moment the mode changes.
"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.reconciliation.infrastructure.models import ReconciliationDiscrepancyRow
from strategy_manager.shared.domain.mode import Mode


class SqlAlchemyReconciledUsers:
    """Read-only: this class has no method that writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def includes(self, user_id: UUID) -> bool:
        return (
            await self._is_live(user_id)
            or bool(await SqlAlchemyLiveExposure(self._session).symbols(user_id))
            or await self._has_open_discrepancy(user_id)
        )

    async def among(self, user_ids: Iterable[UUID]) -> frozenset[UUID]:
        return frozenset([user_id for user_id in user_ids if await self.includes(user_id)])

    async def _is_live(self, user_id: UUID) -> bool:
        mode = await self._session.scalar(select(UserRow.mode).where(UserRow.id == user_id))
        return mode == Mode.LIVE.value

    async def _has_open_discrepancy(self, user_id: UUID) -> bool:
        answer = await self._session.scalar(
            select(
                exists().where(
                    ReconciliationDiscrepancyRow.user_id == user_id,
                    ReconciliationDiscrepancyRow.resolved_at.is_(None),
                )
            )
        )
        return bool(answer)
