"""Ports (Protocols) and consumer-owned DTOs declared by ``execution``,
implemented by ``ledger`` and ``allocation.infrastructure`` (design.md §
Interfaces / Contracts). The consumer declares the port, the provider owns
the adapter — ``FillRecorderPort``/``FillRecord`` are implemented by
``ledger.application.record_fill.RecordFill``; ``ReservationGatewayPort`` is
implemented against the ``reservations`` table ``allocation`` already owns.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderRequest
from strategy_manager.shared.domain.errors import DomainError


class ExchangeError(DomainError):
    """Raised by ``ExchangePort.submit`` when the exchange rejects or errors
    on an order. Distinguishes a business-level rejection from a raised
    ``Fill`` on success (design.md's sequence diagram 3, "exchange rejects
    or errors" branch)."""


class ExchangePort(Protocol):
    """In this change the only registered adapter is ``FakeExchangeAdapter``
    (``is_live = False``). ``is_live`` gates the ``DRY_RUN`` startup
    invariant (spec: trade-execution § DRY_RUN Safety)."""

    is_live: bool

    async def submit(self, order: OrderRequest) -> Fill: ...


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    """What ``ExecuteReservation`` needs to know about the reservation it is
    executing, decoupled from the ``allocation`` module's own aggregate — no
    provider type leaks across the module boundary (mirrors
    ``StrategyPolicySnapshot``)."""

    id: UUID
    strategy_id: UUID
    venue: str
    settlement_currency: str
    amount: Decimal
    status: str
    expires_at: datetime


class ReservationGatewayPort(Protocol):
    """``get_for_update`` MUST take a row lock (``FOR UPDATE``) so the
    pre-submit expiry re-check and the subsequent status write are atomic
    within the caller's open transaction (design.md § TXN-B1)."""

    async def get_for_update(self, reservation_id: UUID) -> ReservationSnapshot: ...

    async def mark(self, reservation_id: UUID, status: str, at: datetime) -> None: ...


class ExecutionAttemptRepositoryPort(Protocol):
    async def insert(self, attempt: ExecutionAttempt) -> None: ...

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None: ...

    async def mark_failed(self, attempt_id: UUID, error: str) -> None: ...


@dataclass(frozen=True, slots=True)
class FillRecord:
    """What ``FillRecorderPort.record`` receives. Carries every field
    ``trade-ledger § Ledger Row Content`` requires, including
    ``usd_rate_at_fill`` already resolved at fill time (CLAUDE.md rule 7 —
    the rate can never be backfilled)."""

    strategy_id: UUID
    allocation_id: UUID
    execution_attempt_id: UUID
    venue: str
    settlement_currency: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    notional: Decimal
    exchange_order_id: str
    exchange_fill_id: str
    filled_at: datetime
    usd_rate_at_fill: Decimal


class FillRecorderPort(Protocol):
    async def record(self, fill: FillRecord) -> None: ...


class CommitPort(Protocol):
    """Mirrors ``allocation.application.ports.CommitPort`` /
    ``signals.application.ports.CommitPort``: deliberately narrow so any
    object with an async ``commit()`` satisfies it structurally."""

    async def commit(self) -> None: ...
