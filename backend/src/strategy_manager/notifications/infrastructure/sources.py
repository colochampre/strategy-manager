"""The adapters behind the notifications' ports (panel-redesign RD.5a): each fills
one port from another module's own read, built the way that module's router
builds it. None of them writes, signs or calls an exchange.

* ``SqlAlchemyOperationSource``: the closed operations come from ``ReadMyTrades``
  (the derivation ``GET /performance/trades`` serves: figures, close causes,
  rehearsal flags) and the open ones from ``ReadOpenPositions`` given NO mark
  source, so no price is asked of any venue. The opening leverage of a closed
  operation is read from its opening attempt in one statement; an open
  operation's is the open positions read's own.
* ``SqlAlchemyRefusalSource``: the safety events of the three refusal kinds.
* ``SqlAlchemyNoticeSource``: the user's rejected deliveries and their strategy.
  ``outcome_detail`` is never selected.
* ``ReconciliationDiscrepancySource``: ``ReadConfirmed``, assembled exactly as
  ``GET /reconciliation/confirmed`` assembles it.
"""

from collections.abc import Collection, Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.mode_origin import Origin
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.notifications.application.ports import (
    ClosedFacts,
    DiscrepancyFacts,
    DiscrepancyReading,
    NoticeFacts,
    OperationFacts,
    RefusalFacts,
)
from strategy_manager.notifications.application.read_notifications import REFUSAL_KINDS
from strategy_manager.performance.application.read_my_trades import ReadMyTrades
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.performance.infrastructure.confirmed_disagreement_source import (
    ConfirmedDisagreementSource,
)
from strategy_manager.performance.infrastructure.my_trades_source import SqlAlchemyMyTradesSource
from strategy_manager.performance.infrastructure.open_position_facts_source import (
    SqlAlchemyOpenPositionFactsSource,
)
from strategy_manager.reconciliation.application.read_confirmed import ReadConfirmed
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.reconciled_users import (
    SqlAlchemyReconciledUsers,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.strategy_name_adapter import (
    StrategyNameAdapter,
)
from strategy_manager.safety.infrastructure.repository import SqlAlchemySafetyEventReader
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.strategies.infrastructure.models import StrategyRow

_REJECTED = "REJECTED"


class SqlAlchemyOperationSource:
    """Implements ``OperationSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def operations(self, user_id: UUID) -> Sequence[OperationFacts]:
        session = self._session
        closed = await ReadMyTrades(
            SqlAlchemyAllocationFillsSource(session), SqlAlchemyMyTradesSource(session)
        ).read_every(user_id)
        leverage = await self._opening_leverage(user_id, [t.trade.allocation_id for t in closed])
        # Given no mark source: the read asks no venue for a price.
        open_now = await ReadOpenPositions(
            SqlAlchemyModeOriginReader(session),
            SqlAlchemyOpenPositionFactsSource(session),
            ConfirmedDisagreementSource(SqlAlchemyDiscrepancyRepository(session)),
        ).read(user_id)

        facts: list[OperationFacts] = []
        for item in closed:
            trade, figures = item.trade, item.figures
            facts.append(
                OperationFacts(
                    allocation_id=trade.allocation_id,
                    strategy_id=trade.strategy_id,
                    strategy_name=item.strategy.name,
                    exchange=trade.exchange,
                    venue=trade.venue,
                    currency=trade.settlement_currency,
                    pair=trade.pair,
                    side=trade.direction.value,
                    rehearsal=item.rehearsal,
                    opened_at=trade.opened_at,
                    entry_price=None if figures is None else figures.entry_price,
                    leverage=leverage.get(trade.allocation_id),
                    closed=ClosedFacts(
                        closed_at=trade.closed_at,
                        exit_price=None if figures is None else figures.exit_price,
                        pnl=trade.pnl,
                        close_cause=item.close_cause.value,
                    ),
                )
            )
        listed = {f.allocation_id for f in facts}
        for position in open_now.positions:
            if position.allocation_id in listed:
                continue
            figures_open = position.figures
            facts.append(
                OperationFacts(
                    allocation_id=position.allocation_id,
                    strategy_id=position.strategy_id,
                    strategy_name=position.strategy_name,
                    exchange=position.pool.exchange,
                    venue=position.pool.venue,
                    currency=position.pool.settlement_currency,
                    pair=position.markets[0] if len(position.markets) == 1 else None,
                    side=None if figures_open is None else figures_open.side.value,
                    rehearsal=position.origin is Origin.REHEARSAL,
                    opened_at=position.opened_at,
                    entry_price=None if figures_open is None else figures_open.entry_price,
                    leverage=position.leverage,
                    closed=None,
                )
            )
        return facts

    async def _opening_leverage(
        self, user_id: UUID, allocation_ids: Sequence[UUID]
    ) -> dict[UUID, Decimal]:
        """The leverage each opening attempt recorded, by reservation (one attempt
        opens a reservation, ``reservation_id`` being unique). An allocation with
        none, spot included, is absent."""
        if not allocation_ids:
            return {}
        rows = await self._session.execute(
            select(ExecutionAttemptRow.reservation_id, ExecutionAttemptRow.leverage).where(
                ExecutionAttemptRow.user_id == user_id,
                ExecutionAttemptRow.reservation_id.in_(allocation_ids),
                ExecutionAttemptRow.leverage.is_not(None),
            )
        )
        return {row[0]: Decimal(row[1]) for row in rows.all()}


class SqlAlchemyRefusalSource:
    """Implements ``RefusalSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._reader = SqlAlchemySafetyEventReader(session)

    async def refusals(self, user_id: UUID) -> Sequence[RefusalFacts]:
        events = await self._reader.of_kinds(user_id, REFUSAL_KINDS)
        return [
            RefusalFacts(
                event_id=e.id,
                kind=e.kind.value,
                strategy_id=e.strategy_id,
                strategy_name=e.strategy_name,
                exchange=e.exchange,
                venue=e.venue,
                symbol=e.symbol,
                occurred_at=e.occurred_at,
                detail=dict(e.detail),
            )
            for e in events
        ]


class SqlAlchemyNoticeSource:
    """Implements ``NoticeSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def notices(self, user_id: UUID, reasons: Collection[str]) -> Sequence[NoticeFacts]:
        rows = await self._session.execute(
            select(
                SignalDeliveryRow.id,
                SignalDeliveryRow.outcome_reason,
                StrategyRow.id,
                StrategyRow.name,
                StrategyRow.exchange,
                StrategyRow.venue,
                StrategyRow.settlement_currency,
                SignalRow.symbol,
                SignalDeliveryRow.decided_at,
            )
            .join(SignalRow, SignalRow.id == SignalDeliveryRow.signal_id)
            .join(StrategyRow, StrategyRow.id == SignalRow.strategy_id)
            .where(
                SignalDeliveryRow.user_id == user_id,
                SignalDeliveryRow.status == _REJECTED,
                SignalDeliveryRow.outcome_reason.in_(list(reasons)),
                SignalDeliveryRow.decided_at.is_not(None),
            )
        )
        return [
            NoticeFacts(
                delivery_id=row[0],
                reason=row[1],
                strategy_id=row[2],
                strategy_name=row[3],
                exchange=row[4],
                venue=row[5],
                currency=row[6],
                symbol=row[7],
                decided_at=row[8],
            )
            for row in rows.all()
        ]


class ReconciliationDiscrepancySource:
    """Implements ``DiscrepancySourcePort``. Whole-system, as the confirmed read
    is: the use case asks for it for an admin only."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def needs_owner(self) -> DiscrepancyReading:
        # ``dry_run`` as ``GET /reconciliation/confirmed`` says it: the brake, or a
        # scan that skips every user (nothing is compared for anyone then).
        dry_run = self._settings.dry_run or not await SqlAlchemyReconciledUsers(
            self._session
        ).anyone()
        if dry_run:
            return DiscrepancyReading(dry_run=True)
        reading = await ReadConfirmed(
            discrepancies=SqlAlchemyDiscrepancyRepository(self._session),
            proposals=SqlAlchemyBookingProposalRepository(self._session),
            names=StrategyNameAdapter(self._session),
            clock=SystemClock(),
            grace_seconds=self._settings.reconciliation_auto_booking_grace_seconds,
            dry_run=dry_run,
        ).read()
        return DiscrepancyReading(
            dry_run=reading.dry_run,
            needs_owner=tuple(
                DiscrepancyFacts(
                    discrepancy_id=d.discrepancy_id,
                    exchange=d.exchange,
                    venue=d.venue,
                    currency=d.settlement_currency,
                    symbol=d.symbol,
                    kind=d.kind.value,
                    occurred_at=d.confirmed_at or d.last_observed_at,
                )
                for d in reading.needs_owner
            ),
        )
