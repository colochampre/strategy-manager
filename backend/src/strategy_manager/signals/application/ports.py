"""Ports (Protocols) owned by ``signals``.

Consumer declares the port, provider owns the adapter — the router (the
composition point for this module) is the only place that binds them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.signals.domain.holding import HeldAllocation
from strategy_manager.signals.domain.signal import WebhookSignal

PoolKey = tuple[str, str, str]
"""A pool's identity: ``(exchange, venue, settlement_currency)``. Mirrors
``accounts.application.ports.PoolKey`` and
``reconciliation.application.ports.PoolKey`` exactly but is redeclared here
rather than imported, so ``signals`` never reaches across another module's
boundary for a bare type alias."""


@dataclass(frozen=True, slots=True)
class InsertOutcome:
    """Result of an idempotent insert: which id, and whether it was new."""

    signal_id: UUID
    inserted: bool


class SignalRepositoryPort(Protocol):
    """Idempotent persistence: ``ON CONFLICT (strategy_id, idempotency_key)
    DO NOTHING`` semantics, resolved to the existing row on conflict."""

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome: ...

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None: ...

    async def find_prior(
        self, strategy_id: UUID, symbol: str, before: datetime
    ) -> WebhookSignal | None:
        """The most recent signal for ``(strategy_id, symbol)`` received
        strictly before ``before`` — backs the "compare against last known
        position_size" lookup ``PositionTransition`` routing needs
        (design.md § "position_size routes the signal")."""
        ...


class WebhookAuthPort(Protocol):
    """Authenticates a webhook request by source IP and shared secret."""

    def authenticate(self, source_ip: str | None, provided_secret: str | None) -> bool: ...


class CommitPort(Protocol):
    """The minimal capability ``IngestSignal`` needs to finalize its
    transaction. Deliberately narrower than ``shared.UnitOfWorkPort`` so any
    object with an async ``commit()`` (including a raw ``AsyncSession``)
    satisfies it structurally, without leaking SQLAlchemy into this layer."""

    async def commit(self) -> None: ...


class SymbolHoldingsPort(Protocol):
    """Reads every strategy's currently open allocations on one market within
    one pool, merged across every spelling that market wears (design.md § S2
    "the query"). Implemented by
    ``ledger.application.read_symbol_holdings.ReadSymbolHoldings``.

    Feeds both the Existing-Position Guard (this strategy's own net, S2) and
    orphan classification (the pool's net over every strategy, S4) from the
    one query design.md says serves both -- so it is declared once here
    rather than twice.
    """

    async def symbol_holdings(
        self, pool: PoolKey, symbol: str
    ) -> list[HeldAllocation]: ...


class InFlightWorkPort(Protocol):
    """Whether the strategy has execution work in flight on this market
    within this pool -- an opening reservation still PENDING within its TTL,
    or a SUBMITTED execution attempt (opening or closing) tied to a
    reservation for this strategy (design.md § "In flight vs orphan").

    Implemented by ``signals.infrastructure.in_flight_work.InFlightWorkAdapter``,
    composing ``execution``'s and ``allocation``'s own repositories -- neither
    module owns the whole answer on its own, since attempts carry no
    ``strategy_id`` and reservations carry no ``symbol``.
    """

    async def in_flight(
        self, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool: ...
