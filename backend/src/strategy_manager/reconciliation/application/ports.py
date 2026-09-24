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
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
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

    async def get(self, discrepancy_id: UUID) -> DiscrepancyRecord:
        """Re-reads one row by id -- what ``ApproveBooking``'s freshness
        re-check (design.md § 7) compares a booking proposal's frozen
        columns against. Not in this port's original inventory (that
        document only lists ``upsert_open``/``resolve_absent``/
        ``list_discrepancies``); added during Unit 6a's apply because none
        of those three answers "re-read THIS discrepancy by id" without
        scanning the whole table. Raises ``InvariantViolation`` if the row
        is gone -- a discrepancy is never deleted, only ``resolved_at``-
        stamped, so a missing row here is a bug, not a business outcome."""
        ...

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


@dataclass(frozen=True, slots=True)
class VenueFill:
    """One venue-reported fill from a WINDOW fetch (design decision 9,
    Blocker c — corrects explore #230 Q3).

    ``execution.domain.fill.Fill`` (seven fields) has no ``side``: an
    order-scoped fetch inherits its side from the order it settled, which
    already carries the direction. A window fetch has no order — it asks a
    venue for everything that happened on a symbol in a time range — so
    ``side`` has to travel on the fill itself. This is a separate DTO, not
    a reuse of ``Fill``.
    """

    exchange_fill_id: str
    exchange_order_id: str | None
    symbol: str
    side: str
    """``'BUY'`` or ``'SELL'``, normalised by the adapter (reader) from
    each venue's own spelling. Never anything else — an unrecognised side
    is a shape the reader has never seen and must not guess at."""
    quantity: Decimal
    """Always positive. A non-positive quantity is refused by the reader
    rather than passed through, the same discipline every venue adapter
    here applies to a fill price or a fee."""
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime
    """Tz-aware UTC."""


class VenueFillReadError(DomainError):
    """Raised by ``VenueFillReaderPort.fills_in_window`` when the live call
    to the venue itself fails, refuses, or answers with something the
    reader cannot safely translate into a ``VenueFill`` (an unrecognised
    side, a non-positive quantity, or — Bybit only — an execution type that
    is neither a known trade type nor ``Funding``).

    Mirrors ``VenuePositionReadError`` exactly: the ONE swallowable error a
    booking sweep may eat per discrepancy, so one market's failed fetch
    skips that discrepancy rather than killing the whole sweep. A registry
    lookup failure for an unserved pool is a *different*, never-swallowed
    exception — the same split ``VenuePositionReadError`` already draws
    against ``UnservedPoolError``.
    """


class VenueFillReaderPort(Protocol):
    """Reads every venue-reported fill for one symbol within a time window —
    the read a booking proposal is built from (design decision 9).

    REMOTE by nature, same caution as ``VenuePositionReaderPort``.

    ``exchange``/``venues`` mirror ``VenuePositionReaderPort``'s own two
    class attributes: ``VenueFillReaderRegistryPort`` is keyed by
    ``(exchange, venue)`` and needs them to route.
    """

    exchange: str
    venues: frozenset[str]

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]: ...


class VenueFillReaderRegistryPort(Protocol):
    """Which reader serves a given pool's fill-window read. Mirrors
    ``VenuePositionReaderRegistryPort`` exactly, including its refusal
    rule: an unserved pool RAISES, there is no fallback."""

    def for_pool(self, exchange: str, venue: str) -> VenueFillReaderPort: ...


@dataclass(frozen=True, slots=True)
class ProposedFillSnapshot:
    """One element of a booking proposal's frozen ``fills`` JSONB array
    (design.md § 3, "The frozen snapshot's exact shape"). Every numeric
    field is a ``Decimal`` here — the repository is the only thing that
    may ever turn one into JSON, and it MUST do so as a STRING, never a
    JSON number, the same rule ``_amount()`` already enforces on the wire:
    a JSON number has already lost the precision an append-only ledger
    depends on."""

    exchange_fill_id: str
    exchange_order_id: str | None
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime
    """Tz-aware UTC, same convention as ``VenueFill.filled_at``."""


@dataclass(frozen=True, slots=True)
class NewBookingProposal:
    """Every frozen column of ``booking_proposals`` (migration ``0023``),
    supplied to ``BookingProposalRepositoryPort.insert``. Server-assigned
    columns (``id``, ``created_at``, ``state``) are absent — the database
    assigns them, and the repository reads them back on a successful
    write."""

    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    """The MARKET KEY, like the discrepancy row it was prepared from
    (design.md § 13) — never a venue spelling."""
    kind: DiscrepancyKind
    """Restricted at the database by ``ck_booking_proposals_kind`` to the
    two BOOKABLE verdicts; this port accepts the full enum because it is
    the type ``Observation.kind`` already carries, and the CHECK is the
    real guard."""
    allocation_id: UUID
    strategy_id: UUID
    side: str
    quantity: Decimal
    observed_venue_net_base: Decimal
    observed_ledger_net_base: Decimal
    observed_allocation_ids: Sequence[UUID]
    fills: Sequence[ProposedFillSnapshot]
    client_order_id: str
    expires_at: datetime
    prepared_by_job_id: UUID


@dataclass(frozen=True, slots=True)
class BookingProposalRecord:
    """One row of ``booking_proposals``, as read back — every frozen column
    plus the five mutable ones (design.md § 3)."""

    id: UUID
    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    allocation_id: UUID
    strategy_id: UUID
    side: str
    quantity: Decimal
    observed_venue_net_base: Decimal
    observed_ledger_net_base: Decimal
    observed_allocation_ids: tuple[UUID, ...]
    fills: tuple[ProposedFillSnapshot, ...]
    client_order_id: str
    expires_at: datetime
    prepared_by_job_id: UUID
    created_at: datetime
    state: str
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    execution_attempt_id: UUID | None


class BookingProposalRepositoryPort(Protocol):
    """Design.md's port inventory, § 3 "Concurrency without a lock table"
    and § 11 "Rejection semantics and suppression". Implemented by
    ``SqlAlchemyBookingProposalRepository`` (Unit 3b).

    The frozen-vs-mutable split documented in migration ``0023``'s own
    docstring is this port's discipline, not the database's: ``insert``
    writes every frozen column exactly once; ``mark_state`` is the ONLY
    method that ever changes ``state``/``decided_at``/``decided_by``/
    ``decision_reason``/``execution_attempt_id``, and nothing else.
    """

    async def insert(self, proposal: NewBookingProposal) -> BookingProposalRecord | None:
        """Writes a fresh PENDING proposal. Returns ``None``, having
        written nothing, when ``ux_booking_proposals_pending_per_discrepancy``
        already holds a PENDING row for this ``discrepancy_id`` — a
        distinguishable, non-raising outcome identified by the violated
        constraint's NAME, never its message text. Any other
        ``IntegrityError`` (a bad FK, a violated CHECK) is a bug and
        propagates. Runs inside its own SAVEPOINT so a caller sweeping
        several discrepancies within one session/transaction can keep
        going after this outcome (design decision 6's identical reasoning
        for ``SqlAlchemyBookingWriter``)."""
        ...

    async def get_for_update(self, proposal_id: UUID) -> BookingProposalRecord:
        """Row-locks the proposal (design.md § 3, "Concurrency without a
        lock table") — the shape ``ReservationGatewayPort.get_for_update``
        already documents: ``SELECT ... FOR UPDATE``, preceding the one
        conditional UPDATE ``mark_state`` performs, inside the same
        transaction."""
        ...

    async def mark_state(
        self,
        proposal_id: UUID,
        state: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        decision_reason: str | None = None,
        execution_attempt_id: UUID | None = None,
    ) -> bool:
        """The repository's ONLY UPDATE: ``... WHERE id=:id AND
        state='PENDING'``, meant to follow ``get_for_update`` in the same
        transaction. Returns whether a row actually changed — ``False``
        means a racing decision already won (design.md § 3's
        ``ALREADY_DECIDED`` outcome), and the caller MUST inspect this
        return value rather than assume success; a 0-row update is a
        legitimate, silent-by-construction outcome that only this return
        value makes visible."""
        ...

    async def list_pending(self, limit: int = 100) -> list[BookingProposalRecord]:
        """PENDING rows only, ordered by ``expires_at`` ascending — the
        admin list endpoint and the expiry sweep are the only two readers
        of ``ix_booking_proposals_pending``, and neither ever needs a
        non-PENDING row (migration ``0023``'s own index docstring)."""
        ...

    async def has_matching_rejection(
        self, discrepancy_id: UUID, observation: Observation
    ) -> bool:
        """design.md § 11's suppression lookup: ``True`` when a REJECTED
        proposal exists for ``discrepancy_id`` whose frozen ``(kind,
        observed_venue_net_base, observed_ledger_net_base)`` equals
        ``observation`` by DECIMAL VALUE equality — reusing the exact
        ``Observation`` triple ``next_consecutive_scans`` already compares
        this way. Reads every state via ``ix_booking_proposals_discrepancy``
        (the non-partial index over ``discrepancy_id``); the suppression
        key is this Observation triple, NEVER the frozen ``fills``
        snapshot."""
        ...

    async def expire_pending(self, now: datetime) -> int:
        """Marks every PENDING row with ``expires_at <= now`` as EXPIRED.
        Returns how many rows actually changed. Called by
        ``ExpireBookingProposals`` (Unit 6b) inside the prepare handler,
        before the sweep."""
        ...


class RecordedFillIdsPort(Protocol):
    """Which of a candidate set of venue-reported fill ids the ledger
    ALREADY holds, keyed on ``(exchange, venue, exchange_fill_id)`` -- NEVER
    on symbol (design.md § 13: a booked close may carry a different
    spelling than the open it nets against, and keying this lookup on
    symbol would reintroduce exactly the mismatch design.md § 13's testing
    rule exists to catch). Mirrors ``ux_ledger_exchange_fill`` (migration
    ``0019``) exactly.

    Implemented by ``ledger``'s ``ReadRecordedFillIds``, sibling of
    ``ReadSymbolPositions`` (design.md's component inventory): the consumer
    (this module) declares the port, the provider (``ledger``) owns the
    adapter, the same direction every other module already uses. Consumed
    by ``domain.booking.match_fills``'s ``already_recorded_ids`` parameter
    (``PrepareBooking``, Unit 4b, resolves it before calling ``match_fills``
    -- the domain layer itself never reaches the ledger).
    """

    async def recorded_fill_ids(
        self, exchange: str, venue: str, exchange_fill_ids: Sequence[str]
    ) -> frozenset[str]: ...


class AllocationOwnerPort(Protocol):
    """Resolves the strategy that owns a still-open allocation -- what a
    booking proposal's ``strategy_id`` column (migration ``0023``) is
    populated from, given the ``allocation_id`` ``classify()`` attributed
    the discrepancy to (design.md's component inventory).

    Implemented by ``AllocationOwnerAdapter``, reading ``reservations``
    directly -- the same cross-module read
    ``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol``
    already performs by importing ``ReservationRow`` from ``allocation``'s
    own infrastructure models.
    """

    async def strategy_for(self, allocation_id: UUID) -> UUID: ...


class InFlightClosePort(Protocol):
    """design.md § 7's freshness re-check, half (g): whether the strategy
    already has a SUBMITTED closing execution attempt on this market within
    this pool -- a signal-originated close racing this approval.

    Implemented by ``InFlightCloseAdapter``, wrapping the EXISTING
    ``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol``
    with NO new SQL (design.md § 7): that method already merges every
    spelling a symbol wears (``market_spellings``) and already answers
    exactly this question for the signals side's own in-flight check.
    """

    async def submitted_for(self, pool: PoolKey, strategy_id: UUID, symbol: str) -> bool: ...


class BookingWriteOutcome(StrEnum):
    """design.md § 6, step 5: ``BookingWritePort.write``'s two expected
    outcomes. ``WRITTEN`` is the ordinary path; ``ALREADY_RECORDED`` is the
    two named-constraint ``IntegrityError`` translations
    (``SqlAlchemyBookingWriter``, Unit 6a), never a third value and never a
    silently-swallowed exception."""

    WRITTEN = "WRITTEN"
    ALREADY_RECORDED = "ALREADY_RECORDED"


@dataclass(frozen=True, slots=True)
class BookingWriteResult:
    outcome: BookingWriteOutcome
    execution_attempt_id: UUID
    """The id ``ApproveBooking`` generated for the ``ExecutionAttempt`` it
    asked ``write`` to persist -- echoed back regardless of outcome, so the
    caller never has to keep its own copy just to log or to pass into
    ``mark_state``."""
    fills_written: int
    """How many ``ledger_entries`` rows were actually inserted. Zero on
    ``ALREADY_RECORDED`` -- the SAVEPOINT rolled the whole attempt-plus-fills
    write back, never a partial set of rows."""
    reason: str | None = None
    """Set only on ``ALREADY_RECORDED``: the violated constraint's name, for
    the WARNING ``ApproveBooking`` logs before marking the proposal
    SUPERSEDED."""


class BookingWritePort(Protocol):
    """design.md § 6, "``ApproveBooking`` -- transaction boundary and the two
    expected IntegrityErrors". Implemented by ``SqlAlchemyBookingWriter``
    (Unit 6a, infrastructure only -- SQLAlchemy and ``IntegrityError`` never
    reach the use case).

    ``write`` inserts exactly one ``execution_attempts`` row (``attempt``,
    already constructed ``origin=VENUE``/``status=FILLED`` by the caller) and
    one ``ledger_entries`` row per element of ``fill_records`` (via the
    EXISTING ``ledger.application.record_fill.RecordFill``, never a second
    ledger-writing code path), inside its own SAVEPOINT
    (``session.begin_nested()``) nested in the caller's open transaction.

    Exactly two ``IntegrityError``s are expected, identified by CONSTRAINT
    NAME, never message text: ``execution_attempts_client_order_id_key`` (a
    replayed approval colliding with itself) and ``ux_ledger_exchange_fill``
    (someone else already recorded this fill). Both translate to
    ``ALREADY_RECORDED``, having rolled the SAVEPOINT back to before this
    call -- the caller's transaction stays open and usable (design.md § 6's
    own "the SAVEPOINT is load-bearing" argument). Any other
    ``IntegrityError`` -- an FK violation, a CHECK violation, the
    append-only trigger -- is a bug and propagates unchanged.
    """

    async def write(
        self, attempt: ExecutionAttempt, fill_records: Sequence[FillRecord]
    ) -> BookingWriteResult: ...
