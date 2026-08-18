"""SQLAlchemy implementation of ``ReservationRepositoryPort`` against the
``reservations`` table (migration ``0004``).
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.shared.domain.money import Currency, Venue

_ACTIVE_STATUSES = (ReservationStatus.PENDING.value, ReservationStatus.SUBMITTED.value)


def _to_domain(row: ReservationRow) -> Reservation:
    return Reservation(
        id=row.id,
        strategy_id=row.strategy_id,
        signal_id=row.signal_id,
        pool_key=PoolKey(
            venue=Venue(row.venue), settlement_currency=Currency(row.settlement_currency)
        ),
        amount=row.amount,
        status=ReservationStatus(row.status),
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyReservationRepository:
    """Implements ``allocation.application.ReservationRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        row = (
            await self._session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def get_for_update(self, reservation_id: UUID) -> Reservation:
        """Row-locks the reservation (spec: trade-execution; design.md §
        TXN-B1). Used by ``execution``'s pre-submit expiry re-check via
        ``ReservationGatewayAdapter``, which owns this method's cross-module
        boundary."""

        row = (
            await self._session.execute(
                select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update()
            )
        ).scalar_one()
        return _to_domain(row)

    async def sum_active(self, venue: str, settlement_currency: str, now: datetime) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(ReservationRow.amount), 0)).where(
                ReservationRow.venue == venue,
                ReservationRow.settlement_currency == settlement_currency,
                ReservationRow.status.in_(_ACTIVE_STATUSES),
                ReservationRow.expires_at > now,
            )
        )
        return Decimal(result.scalar_one())

    async def insert(self, reservation: Reservation) -> None:
        self._session.add(
            ReservationRow(
                id=reservation.id,
                strategy_id=reservation.strategy_id,
                signal_id=reservation.signal_id,
                venue=reservation.pool_key.venue.value,
                settlement_currency=reservation.pool_key.settlement_currency.value,
                amount=reservation.amount,
                status=reservation.status.value,
                expires_at=reservation.expires_at,
            )
        )
        await self._session.flush()

    async def mark(self, reservation_id: UUID, status: ReservationStatus, at: datetime) -> None:
        await self._session.execute(
            update(ReservationRow)
            .where(ReservationRow.id == reservation_id)
            .values(status=status.value, updated_at=at)
        )
