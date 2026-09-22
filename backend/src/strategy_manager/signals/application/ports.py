"""Ports (Protocols) owned by ``signals``.

Consumer declares the port, provider owns the adapter — the router (the
composition point for this module) is the only place that binds them.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
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

    async def has_newer(self, strategy_id: UUID, symbol: str, received_at: datetime) -> bool:
        """Whether ``strategy_id`` has a LATER signal on this market than
        ``received_at`` — merged across every spelling ``symbol`` wears
        (``market_spellings``) — backing the continuation's abandonment
        check (design.md § S5; spec: job-queue § Continuation Abandonment,
        "a newer signal has arrived"). Strictly later: an equal timestamp is
        the same signal, not a newer one, and must not abandon anything.

        Scoped to strategy AND symbol (owner decision, this unit): a newer
        signal for the same strategy on a DIFFERENT symbol, or for a
        different strategy on the SAME symbol, must not abandon this
        continuation.
        """
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

    async def submitted_closing_allocations(
        self, pool: PoolKey, strategy_id: UUID, symbol: str
    ) -> list[UUID]:
        """The allocation id(s) whose closing execution attempt is currently
        SUBMITTED for this strategy and symbol -- what the rewired in-flight
        branch of ``HoldingGuard`` awaits via ``OpenAfterClose`` instead of
        raising into the queue's failure backoff (design.md § S5, amending
        S2). Empty when ``in_flight`` is True for a different reason (an
        opening attempt in flight, or a PENDING reservation with no attempt
        yet) -- there is nothing to await settling in that case, and the
        continuation re-checks from scratch on its own cadence instead.

        Implemented by
        ``signals.infrastructure.in_flight_work.InFlightWorkAdapter``.
        """
        ...


class RefreshStatus(Enum):
    """The three outcomes of an on-demand balance refresh (design.md § S3).

    FRESH: the remote read succeeded and the new snapshot was written.
    FALLBACK: the read failed but the existing snapshot is still young enough
    to size against. UNAVAILABLE: the read failed and the existing snapshot
    (or its absence) is too old to trust -- the signal must be refused.
    """

    FRESH = "FRESH"
    FALLBACK = "FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """``age_seconds`` is populated for FALLBACK (always) and UNAVAILABLE
    (unless the pool was never synced at all, in which case there is no age
    to report). ``reason`` carries the reader's own failure text; absent on
    FRESH, since nothing failed."""

    status: RefreshStatus
    age_seconds: float | None = None
    reason: str | None = None


class BalanceRefreshPort(Protocol):
    """On-demand balance refresh for exactly one pool, called in
    ``_handle_consumes`` after the Existing-Position Guard and before the
    sizing read -- the last remote call before the advisory lock (design.md §
    S3, "Every remote read happens before ``_lock.acquire``"). NEVER called at
    webhook ingress (CLAUDE.md rule 3).

    Implemented by ``accounts.application.refresh_pool_balance.RefreshPoolBalance``.
    """

    async def refresh(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> RefreshOutcome: ...


class VenueNetPositionPort(Protocol):
    """The ONE remote read the Existing-Position Guard's divergent branch
    makes, right before orphan classification (spec: capital-allocation §
    Orphan Classification; design.md § S4) -- before the pool's advisory
    lock is ever touched, exactly like ``BalanceRefreshPort`` above.

    ``None`` means the read could not be trusted: an unserved pool, a
    transport failure, or the read's own timeout. The caller MUST treat that
    as AMBIGUOUS (``classify_orphan`` already does) -- this port NEVER
    raises out of the guard.

    Implemented by
    ``signals.infrastructure.venue_net_position.VenueNetPositionAdapter``.
    """

    async def net_position(self, pool: PoolKey, symbol: str) -> Decimal | None: ...
