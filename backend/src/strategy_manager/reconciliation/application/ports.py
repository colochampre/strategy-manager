"""Ports (Protocols) and consumer-owned DTOs declared by ``reconciliation``,
implemented by ``ledger``, ``execution``/venue infrastructure, and
``reconciliation.infrastructure`` itself (design.md's component inventory
§ Interfaces). Consumer declares the port, provider owns the adapter — same
direction every other module already uses.

Phase 3 declares every port ``ScanPools`` needs; the concrete adapters
(the venue position readers, ``ledger``'s ``ReadSymbolPositions``, the
SQLAlchemy-backed discrepancy repository) are Phase 4.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.domain.positions import LedgerPosition, VenuePosition
from strategy_manager.shared.domain.errors import DomainError

PoolKey = tuple[str, str, str]
"""A pool's identity: ``(exchange, venue, settlement_currency)``. Mirrors
``accounts.application.ports.PoolKey`` exactly but is redeclared here rather
than imported, so ``reconciliation`` never reaches across another module's
boundary for a bare type alias."""


class VenuePositionReadError(DomainError):
    """Raised by ``VenuePositionReaderPort.open_positions`` when the live
    call to the venue itself fails: network, auth, rate limit, or a
    malformed response.

    This is exactly the exception ``ScanPools`` catches per pool (design
    decision 8): a reconciliation chain must not die because one venue read
    failed on one poll. A lookup failure from
    ``VenuePositionReaderRegistryPort.for_pool`` for an unserved pool is a
    configuration/programming error, is a *different* exception, and is
    never swallowed — it must be loud, exactly like
    ``VenueExchangeRegistry.for_pool`` already behaves for the execution
    side.
    """


class VenuePositionReaderPort(Protocol):
    """Reads a pool's live venue-reported net positions: ONE call per WHOLE
    pool, every symbol at once, mirroring
    ``ExchangeBalanceReaderPort``'s "one call, not N" shape rather than
    ``HeldPositionPort``'s per-allocation one.

    REMOTE by nature. MUST never be called while a pool advisory lock is
    held — the same rule ``ExchangeBalanceReaderPort`` already states for
    the analogous balance read.

    ``exchange``/``venues`` mirror ``ExchangePort``'s own two class
    attributes exactly, and exist for the same reason:
    ``VenuePositionReaderRegistryPort`` is keyed by ``(exchange, venue)``,
    and a registry has to be able to ask a reader which pools it serves
    before it can route to it (Phase 4 addition to this Protocol, mirroring
    ``VenueExchangeRegistry``'s construction-time wiring on the execution
    side).
    """

    exchange: str
    venues: frozenset[str]

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]: ...


class VenuePositionReaderRegistryPort(Protocol):
    """Which reader serves a given pool. Mirrors
    ``execution.application.ports.ExchangeRegistryPort`` exactly, including
    its refusal rule: an unserved pool RAISES, there is no fallback
    (CLAUDE.md's venue-registry rule, restated here for the read side)."""

    def for_pool(self, exchange: str, venue: str) -> VenuePositionReaderPort: ...


class LedgerSymbolPositionPort(Protocol):
    """Reads every symbol with at least one open allocation for a pool, in
    ONE query per pool — unlike ``LedgerPositionReaderPort.net_base_quantity``,
    which is one query PER allocation, because that method answers "what
    does THIS allocation hold" and this one answers "what does this WHOLE
    POOL hold, broken down by symbol".

    Returns one ``LedgerPosition`` per symbol, each already carrying every
    open allocation on it. ``LedgerPosition.net_base`` — the domain layer,
    not this port — folds those entries into the symbol total, and
    ``.allocation_ids`` is exactly what
    ``reconciliation_discrepancies.open_allocation_ids`` stores (design
    decision 2). Nothing in ``reconciliation`` re-sums these values; the
    fold already exists in ``reconciliation.domain.positions``.

    Implemented by ``ledger``'s ``ReadSymbolPositions`` (Phase 4), which
    owns the fee rule too (design decision 4): a fill's quantity is
    subtracted from an allocation's running net base only when that fill's
    ``fee_currency`` differs from the pool's own settlement currency —
    keyed on the fee's currency, never on parsing a base currency out of
    the symbol, because a per-symbol aggregate never receives a
    ``base_currency`` the way ``net_base_quantity(allocation_id,
    base_currency)`` does. Provably a no-op on USDⓈ-M today; load-bearing
    for a future spot/COIN-M pool where a fee IS paid in the base currency.
    """

    async def net_positions_by_symbol(self, pool: PoolKey) -> list[LedgerPosition]: ...


@dataclass(frozen=True, slots=True)
class DiscrepancyRecord:
    """One row of ``reconciliation_discrepancies``, as read back. Mirrors the
    migration's columns exactly, excluding the generated ``delta_base`` —
    it is computed by the database and no caller ever writes or
    reconstructs it."""

    id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    venue_net_base: Decimal
    ledger_net_base: Decimal
    open_allocation_ids: tuple[UUID, ...]
    consecutive_scans: int
    status: DiscrepancyStatus
    first_observed_at: datetime
    last_observed_at: datetime
    confirmed_at: datetime | None
    resolved_at: datetime | None
    first_scan_id: UUID
    last_scan_id: UUID
    resolved_by_scan_id: UUID | None


class DiscrepancyRepositoryPort(Protocol):
    """Design.md's port inventory: ``upsert_open`` / ``resolve_absent`` /
    ``list_discrepancies``.

    ``list_discrepancies`` does double duty. ``ScanPools`` calls it once per
    pool, at the start of that pool's own comparison, with ``open_only=True``
    to learn what was already open — the domain layer
    (``next_consecutive_scans``) needs that previous ``Observation`` to
    decide whether a new one is a continuation or a fresh one; this port
    only fetches it. A future read-only endpoint (Phase 5+) calls the same
    method unfiltered, or with ``status=DiscrepancyStatus.CONFIRMED``, for
    the operator view.
    """

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]: ...

    async def upsert_open(
        self,
        pool: PoolKey,
        symbol: str,
        observation: Observation,
        open_allocation_ids: Sequence[UUID],
        consecutive_scans: int,
        status: DiscrepancyStatus,
        scan_id: UUID,
        at: datetime,
    ) -> None:
        """Writes the single OPEN (``resolved_at IS NULL``) row for
        ``pool``+``symbol`` — insert on the first observation, update in
        place afterward; the partial unique index
        (``ux_reconciliation_open_per_symbol``) enforces there is ever only
        one. ``consecutive_scans`` and ``status`` are already decided by the
        caller via ``next_consecutive_scans``/``derive_status``; this port
        only persists that decision. Implementations MUST set
        ``confirmed_at`` the first time ``status`` becomes ``CONFIRMED`` and
        MUST NOT overwrite it on a later call (migration ``0020``'s
        ``ck_reconciliation_discrepancies_confirmed_at``)."""
        ...

    async def resolve_absent(
        self,
        pool: PoolKey,
        symbols: Sequence[str],
        scan_id: UUID,
        at: datetime,
    ) -> int:
        """Resolves the OPEN row, if any, for every symbol in ``symbols`` —
        called the moment a scan finds a symbol back in agreement, or finds
        it vanished entirely from both the venue and the ledger (spec:
        reconciliation-scan's automatic-resolution requirement). A no-op,
        not an error, for a symbol with no open row. Returns how many rows
        were actually resolved."""
        ...


class CommitPort(Protocol):
    """Mirrors every other module's narrow ``CommitPort`` — deliberately
    small so any object with an async ``commit()`` satisfies it
    structurally."""

    async def commit(self) -> None: ...
