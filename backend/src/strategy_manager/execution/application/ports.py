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
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.placeable import PlaceableOrder
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


@dataclass(frozen=True, slots=True)
class OpenOrderSpec:
    """What an adapter needs to turn granted capital into an opening order.

    ``granted`` is the reservation's amount in the pool's settlement currency
    and ``price`` is the alert's bar-close reference. What those two become
    is venue business, which is exactly why this is a spec handed to an
    adapter rather than an order built by the caller: on spot a buy carries
    ``granted`` verbatim as a quote amount, while on futures ``granted`` is
    margin and the size is ``granted * leverage / price`` at a leverage only
    the adapter can read.
    """

    client_order_id: str
    symbol: str
    side: OrderSide
    granted: Decimal
    price: Decimal


@dataclass(frozen=True, slots=True)
class CloseOrderSpec:
    """What an adapter needs to turn a held position into a closing order.

    ``base_size`` comes from the ledger (``HeldPositionPort``) and is already
    the honest number, so no venue re-derives it. What differs is what the
    venue does with it: spot sells the base currency, futures sends a
    reduce-only order in the closing direction.
    """

    client_order_id: str
    symbol: str
    side: OrderSide
    base_size: Decimal


class ExchangePort(Protocol):
    """``is_live`` gates the ``DRY_RUN`` startup invariant
    (spec: trade-execution § DRY_RUN Safety).

    ``venues`` declares which ``capital_pools.venue`` values this adapter can
    actually trade, and gates the venue startup invariant. It has to be
    declared rather than assumed because Pionex's spot and futures APIs are
    different base paths — ``/api/v1/`` and ``/uapi/v1/`` — and therefore
    different adapters. Without it, a strategy configured on a futures pool
    has its capital sized against the futures wallet and its orders sent to
    spot, with nothing anywhere reporting a problem.

    Both are class attributes so the composition root can check them before an
    instance exists: a live adapter needs a decrypted credential and an open
    socket, and neither belongs to startup.

    Split in two on purpose. ``place`` sends the order; ``fetch_fills``
    learns what became of it, keyed by the client order id this system chose
    before it ever spoke to the exchange. That key is what makes an order
    recoverable when the worker dies mid-flight.

    **Building the order is the adapter's job, not the caller's.** A market
    order is denominated differently per venue -- spot spends a quote amount
    on a buy and sells a base size, futures sends a base size both ways at a
    leverage that must be read from the account -- and only the adapter knows
    which. The two ``build_*`` methods are async for that reason: a futures
    adapter has to ask the venue what leverage the symbol is on before it can
    size anything.

    They stay separate from ``place`` because the caller must record the size
    in its own transaction BEFORE the network call, so the order it commits
    to is the order that goes out.

    ``exchange`` names which one this adapter speaks to. A venue alone stopped
    identifying an adapter the moment two exchanges offered the same one: Bybit
    and Binance both trade ``usdt-m``, and routing a Binance pool's order by
    venue would send it to whichever adapter happened to claim that venue —
    the same class of failure the venue registry was built to prevent, one
    level up.
    """

    is_live: bool
    exchange: str
    venues: frozenset[str]

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder: ...

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder: ...

    async def place(self, order: PlaceableOrder) -> PlacedOrder: ...

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]: ...


class ExchangeRegistryPort(Protocol):
    """Which adapter trades a given pool.

    Every use case that touches an exchange takes this rather than a single
    ``ExchangePort``, because every one of them already knows the pool it is
    acting on -- the reservation's, the close command's, the attempt's -- and
    that pool is the only thing that decides where an order may go.

    Handing a use case one adapter is what allowed a ``usdt-m`` reservation to
    be sized against the futures wallet and placed on spot: the venue reached
    every layer and selected nothing. The exchange joins the key for the same
    reason, one level up: two exchanges now offer ``usdt-m``, and a pool's
    money only exists on one of them.
    """

    def for_pool(self, exchange: str, venue: str) -> ExchangePort: ...


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    """What ``ExecuteReservation`` needs to know about the reservation it is
    executing, decoupled from the ``allocation`` module's own aggregate — no
    provider type leaks across the module boundary (mirrors
    ``StrategyPolicySnapshot``)."""

    id: UUID
    strategy_id: UUID
    exchange: str
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
    exchange: str
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
    """The SIGNED base-currency position an allocation still holds.

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

    **The sign is the direction, and it is load-bearing.** Positive is long:
    more of the base currency was bought than sold. Negative is SHORT, which
    on a futures venue is an ordinary position opened by a SELL and closed by
    buying the same quantity back. Clamping it at zero — which is right for
    spot, where a negative holding really is a bookkeeping impossibility —
    would report every short as "nothing held", and a close sized from that
    can never be placed. The position would stay open at the venue with the
    system unable to exit it.

    So the sign travels, and the caller decides what it may mean for the venue
    it is on.
    """

    async def net_base(self, allocation_id: UUID, base_currency: str) -> Decimal: ...


class CommitPort(Protocol):
    """Mirrors ``allocation.application.ports.CommitPort`` /
    ``signals.application.ports.CommitPort``: deliberately narrow so any
    object with an async ``commit()`` satisfies it structurally."""

    async def commit(self) -> None: ...
