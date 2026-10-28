"""SQLAlchemy implementation of ``ReservationRepositoryPort`` against the
``reservations`` table (migration ``0004``).

**A reservation belongs to a user and to that user's pool** (migration ``0030``,
multi-user design AD2 and AD8). ``insert`` writes the owner and the id of the
owner's pool on the reservation's market, and refuses a market that user holds no
pool on. Every read a scoped caller makes takes ``user_id`` and filters on it, so
another user's reservation on the same market is never returned, counted or
changed.

Three methods stay global, each by design and each saying so: ``expire_due`` is
the worker's sweep over every user's reservations, and ``live_for_strategy`` and
``count_for_strategy`` serve the admin's archive and delete of a strategy, which
is one object for every user.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import (
    ReleaseReason,
    Reservation,
    ReservationStatus,
)
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

_ACTIVE_STATUSES = (ReservationStatus.PENDING.value, ReservationStatus.SUBMITTED.value)


def _to_domain(row: ReservationRow) -> Reservation:
    return Reservation(
        id=row.id,
        strategy_id=row.strategy_id,
        signal_id=row.signal_id,
        pool_key=PoolKey(
            exchange=Exchange(row.exchange),
            venue=Venue(row.venue),
            settlement_currency=Currency(row.settlement_currency),
        ),
        amount=row.amount,
        status=ReservationStatus(row.status),
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        pool_total_at_open=row.pool_total_at_open,
        delivery_id=row.delivery_id,
    )


class SqlAlchemyReservationRepository:
    """Implements ``allocation.application.ReservationRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_signal_id(self, user_id: UUID, signal_id: UUID) -> Reservation | None:
        row = (
            await self._session.execute(
                select(ReservationRow).where(
                    ReservationRow.user_id == user_id, ReservationRow.signal_id == signal_id
                )
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def get_for_update(self, user_id: UUID, reservation_id: UUID) -> Reservation:
        """Row-locks ``user_id``'s reservation (spec: trade-execution; design.md
        § TXN-B1). Used by ``execution``'s pre-submit expiry re-check via
        ``ReservationGatewayAdapter``, which owns this method's cross-module
        boundary. Another user's reservation under that id raises exactly as a
        missing one does."""

        row = (
            await self._session.execute(
                select(ReservationRow)
                .where(ReservationRow.id == reservation_id, ReservationRow.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one()
        return _to_domain(row)

    async def sum_active(
        self,
        user_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
        now: datetime,
    ) -> Decimal:
        """What ``user_id``'s pool on this market has reserved: another user's
        reservations on the same market hold that user's capital, not this one's."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(ReservationRow.amount), 0)).where(
                ReservationRow.user_id == user_id,
                ReservationRow.exchange == exchange,
                ReservationRow.venue == venue,
                ReservationRow.settlement_currency == settlement_currency,
                ReservationRow.status.in_(_ACTIVE_STATUSES),
                ReservationRow.expires_at > now,
            )
        )
        return Decimal(result.scalar_one())

    async def insert(self, user_id: UUID, reservation: Reservation) -> None:
        """Writes ``reservation`` as ``user_id``'s, in that user's pool on its
        market. Raises, before writing anything, when the user holds no pool
        there: the composite FK would refuse the row anyway, and naming the user
        and the market says why. Raises too when the reservation names no
        delivery: every reservation serves one (migration ``0032``)."""
        if reservation.delivery_id is None:
            raise InvariantViolation(
                f"reservation {reservation.id} names no delivery; a reservation always "
                "serves the delivery of one signal to one subscription"
            )
        pool_id = (
            await self._session.execute(
                select(CapitalPoolRow.id).where(
                    CapitalPoolRow.user_id == user_id,
                    CapitalPoolRow.exchange == reservation.pool_key.exchange.value,
                    CapitalPoolRow.venue == reservation.pool_key.venue.value,
                    CapitalPoolRow.settlement_currency
                    == reservation.pool_key.settlement_currency.value,
                )
            )
        ).scalar_one_or_none()
        if pool_id is None:
            raise InvariantViolation(
                f"user {str(user_id)[:8]} has no pool on "
                f"({reservation.pool_key.exchange.value}, {reservation.pool_key.venue.value}, "
                f"{reservation.pool_key.settlement_currency.value}); reservation "
                f"{reservation.id} cannot hold capital in a pool that does not exist"
            )
        self._session.add(
            ReservationRow(
                id=reservation.id,
                user_id=user_id,
                pool_id=pool_id,
                strategy_id=reservation.strategy_id,
                signal_id=reservation.signal_id,
                delivery_id=reservation.delivery_id,
                exchange=reservation.pool_key.exchange.value,
                venue=reservation.pool_key.venue.value,
                settlement_currency=reservation.pool_key.settlement_currency.value,
                amount=reservation.amount,
                status=reservation.status.value,
                expires_at=reservation.expires_at,
                pool_total_at_open=reservation.pool_total_at_open,
            )
        )
        await self._session.flush()

    async def expire_due(self, now: datetime, limit: int) -> int:
        """Implements ``ReservationSweepPort`` — TXN-C (design.md
        § Transaction Boundaries). One set-based UPDATE, never a read-modify-
        write loop: loading each row and transitioning it individually would
        reintroduce exactly the read-then-write race the advisory lock exists
        to prevent, on the one path that deliberately runs without it.

        **Global by design** (multi-user design AD8): the sweeper is the
        worker's own housekeeping over every user's reservations. Expiry is a
        property of the row, not of whose it is, and no user context exists on
        this path.

        Idempotent by construction: the WHERE clause only matches rows that
        still hold capital, so a second pass over the same rows matches nothing
        and leaves ``terminal_at`` — the only record of when a reservation
        actually ended — untouched.

        ``SKIP LOCKED`` keeps two sweepers from blocking on each other; a row
        another sweeper already holds is simply left for the next tick.
        """

        due = (
            select(ReservationRow.id)
            .where(
                ReservationRow.status.in_(_ACTIVE_STATUSES),
                ReservationRow.expires_at <= now,
            )
            .order_by(ReservationRow.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ReservationRow)
                .where(ReservationRow.id.in_(due.scalar_subquery()))
                .values(
                    status=ReservationStatus.EXPIRED.value,
                    terminal_at=now,
                    release_reason=ReleaseReason.EXPIRED_BY_SWEEPER.value,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return result.rowcount

    async def mark(
        self, user_id: UUID, reservation_id: UUID, status: ReservationStatus, at: datetime
    ) -> None:
        """Sets the status of ``user_id``'s reservation. Raises when no such
        row exists: every caller has just read it with ``get_for_update`` under
        the same user, so a miss is a mismatched owner, and a status left
        unwritten would hold capital until the reservation expires with
        nothing saying why."""
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ReservationRow)
                .where(ReservationRow.id == reservation_id, ReservationRow.user_id == user_id)
                .values(status=status.value, updated_at=at)
            ),
        )
        if result.rowcount != 1:
            raise InvariantViolation(
                f"no reservation {reservation_id} of user {str(user_id)[:8]} to mark "
                f"{status.value}"
            )

    async def has_pending_for_strategy(
        self,
        user_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
        strategy_id: UUID,
        now: datetime,
    ) -> bool:
        """Implements ``signals.infrastructure.in_flight_work``'s half (b) of
        the "In flight vs orphan" check (design.md § "the query"):
        strategy-level rather than per-symbol, because reservations carry no
        symbol -- bounded by the reservation's own TTL, so it cannot block an
        opening signal for longer than that. Only ``user_id``'s reservations
        count: another user's work on the same strategy and market is not this
        user's in-flight work (multi-user design AD8).

        Only PENDING counts here, not SUBMITTED: once a reservation reaches
        SUBMITTED, an execution attempt row exists for it, and that is what
        the SUBMITTED-attempt half of the join already catches.

        ``expires_at > now`` is the whole guard against an EXPIRED PENDING
        row: the sweeper (``reservation.sweep``) only flips ``status`` to
        ``EXPIRED`` on its own cadence, so a PENDING row past its TTL must
        still be excluded here rather than trusted to have been swept
        already.
        """
        result = await self._session.execute(
            select(ReservationRow.id)
            .where(
                ReservationRow.user_id == user_id,
                ReservationRow.exchange == exchange,
                ReservationRow.venue == venue,
                ReservationRow.settlement_currency == settlement_currency,
                ReservationRow.strategy_id == strategy_id,
                ReservationRow.status == ReservationStatus.PENDING.value,
                ReservationRow.expires_at > now,
            )
            .limit(1)
        )
        return result.first() is not None

    async def live_for_pool(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> list[UUID]:
        """Every reservation still holding capital in ``user_id``'s pool on this
        market, whichever strategy owns it: ``live_for_strategy`` without the
        strategy filter, with the same ``terminal_at IS NULL`` reading and for
        the same reason. Used by the pool-wide exposure check that guards
        deleting an exchange's key (owner decision 22): the key deleted is that
        user's, so only that user's reservations stand in its way."""
        result = await self._session.execute(
            select(ReservationRow.id).where(
                ReservationRow.user_id == user_id,
                ReservationRow.exchange == exchange,
                ReservationRow.venue == venue,
                ReservationRow.settlement_currency == settlement_currency,
                ReservationRow.status.in_(_ACTIVE_STATUSES),
                ReservationRow.terminal_at.is_(None),
            )
        )
        return [row[0] for row in result.all()]

    async def live_for_strategy(
        self, exchange: str, venue: str, settlement_currency: str, strategy_id: UUID
    ) -> list[UUID]:
        """Every reservation still holding capital for this strategy in this
        pool -- ``status IN (PENDING, SUBMITTED) AND terminal_at IS NULL``
        (design.md § 8's exposure query shape, tasks.md 2c.11/2c.12),
        exactly ``StrategyExposurePort.exposure``'s ``live_reservations``.

        **Global by design, whoever's the reservation** (multi-user design AD8,
        owner decision 16): its one caller is the admin's archive of a
        strategy, and a strategy is one object for every user, so any user's
        live reservation on it must still refuse the archive.

        Deliberately NOT ``has_pending_for_strategy``'s ``expires_at > now``
        criterion: that method exists to bound how long an OPENING signal
        keeps deferring on in-flight work, and a reservation past its TTL
        but not yet swept is intentionally excluded there. Here the
        question is different -- "does this row still hold capital right
        now, as far as the row itself says" -- and ``terminal_at IS NULL``
        answers it directly without depending on the sweeper's cadence: a
        PENDING row past expiry that the sweeper has not yet reached still
        holds capital until something terminates it, so archive must still
        see it and refuse.
        """
        result = await self._session.execute(
            select(ReservationRow.id).where(
                ReservationRow.exchange == exchange,
                ReservationRow.venue == venue,
                ReservationRow.settlement_currency == settlement_currency,
                ReservationRow.strategy_id == strategy_id,
                ReservationRow.status.in_(_ACTIVE_STATUSES),
                ReservationRow.terminal_at.is_(None),
            )
        )
        return [row[0] for row in result.all()]

    async def count_for_strategy(self, strategy_id: UUID) -> int:
        """How many reservations exist for this strategy, in any status and in
        ANY pool -- terminal rows and a row in another pool count too.
        Read-only: ``StrategyHistoryPort``'s ``reservations`` count
        (design.md addendum 9x, § C).

        **Global by design, whoever's the reservation** (multi-user design AD8,
        owner decision 16): its one caller is the admin's delete of a strategy,
        and any user's reservation is history that refuses it (and that the FK
        would refuse at the delete itself)."""
        result = await self._session.execute(
            select(func.count())
            .select_from(ReservationRow)
            .where(ReservationRow.strategy_id == strategy_id)
        )
        return result.scalar_one()
