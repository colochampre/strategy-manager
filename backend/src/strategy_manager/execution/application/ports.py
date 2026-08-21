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
    """Raised by ``ExchangePort`` when the exchange rejects or errors on an
    order (design.md's sequence diagram 3, "exchange rejects or errors"
    branch)."""


class OrderNotFound(DomainError):
    """The exchange has no order under this ``client_order_id``.

    Means the order never reached it. Because the client order id is written
    to the database before the network call, this is the answer that
    distinguishes "we crashed before placing" from "we crashed after
    placing" — and it is the only way to tell them apart after the fact.
    """


class FillsNotReady(DomainError):
    """The exchange accepted the order but has not published its fills yet.

    Transient by nature: the settlement job raises this so the queue retries
    it, rather than concluding the order did not fill.
    """


@dataclass(frozen=True, slots=True)
class PlacedOrder:
    """What the exchange returns when it accepts an order.

    Nothing about the fill is known at this point — Pionex answers a new
    order with an id and nothing else — which is why settlement is a
    separate step rather than the tail of this one.
    """

    exchange_order_id: str
    client_order_id: str


class ExchangePort(Protocol):
    """``is_live`` gates the ``DRY_RUN`` startup invariant
    (spec: trade-execution § DRY_RUN Safety).

    Split in two on purpose. ``place`` sends the order; ``fetch_fills``
    learns what became of it, keyed by the client order id this system chose
    before it ever spoke to the exchange. That key is what makes an order
    recoverable when the worker dies mid-flight.
    """

    is_live: bool

    async def place(self, order: OrderRequest) -> PlacedOrder: ...

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]: ...


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

    async def get(self, attempt_id: UUID) -> ExecutionAttempt: ...

    async def mark_placed(self, attempt_id: UUID, exchange_order_id: str) -> None: ...

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


class HeldPositionPort(Protocol):
    """How much base currency an allocation is still holding.

    Declared here and implemented by ``ledger`` (``ReadHeldBase``), same
    direction as ``FillRecorderPort``: the consumer owns the port, the provider
    owns the adapter.

    This is the only honest source for a close size. The reservation knows what
    was *granted* in the settlement currency, and dividing that by a later
    price does not reproduce what was actually bought — the fill price differs
    from the alert's reference price, a market order can fill in pieces at
    several prices, and a fee charged in the base currency means less of it
    arrived than was purchased. The ledger recorded every one of those facts at
    the time (CLAUDE.md rule 6: positions are a projection over it).
    """

    async def base_held(self, allocation_id: UUID, base_currency: str) -> Decimal: ...


class CommitPort(Protocol):
    """Mirrors ``allocation.application.ports.CommitPort`` /
    ``signals.application.ports.CommitPort``: deliberately narrow so any
    object with an async ``commit()`` satisfies it structurally."""

    async def commit(self) -> None: ...
