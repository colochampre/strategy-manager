"""``PrepareBooking`` — the use case that freezes a booking proposal from a
CONFIRMED attributable discrepancy (design.md's component inventory
§ reconciliation/application/prepare_booking.py; design decisions 1, 5, 9,
11, 13, 16; spec: venue-close-booking, venue-reconciliation).

Fakes only (Unit 4b's own gate; the real Postgres/HTTP wiring is Unit 5).
Money-critical: nothing here may ever write to the ledger or an execution
attempt, and an unbookable verdict (``AMBIGUOUS_PARTIAL_REDUCE``,
``NO_MATCHING_ALLOCATION``) must never be proposed. Both are proven
non-vacuous below (see the module-level note near
``test_prepare_writes_no_ledger_or_execution_rows`` and
``test_ambiguous_partial_reduce_and_no_matching_allocation_never_proposed``):
the RED phase of this file's own history planted the exact bugs these two
tests exist to catch (skipping the ``BOOKABLE_KINDS`` gate; auto-approving a
freshly inserted proposal via ``mark_state``) and observed both assertions
fail before the corresponding fix landed.

Every cross-boundary test uses a DIFFERENT spelling on each side (design
decision 13's testing rule) — a test using one spelling everywhere proves
nothing.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.ports import (
    AllocationOwnerPort,
    BookingProposalRecord,
    DiscrepancyRecord,
    NewBookingProposal,
    PoolKey,
    VenueFill,
    VenueFillReadError,
)
from strategy_manager.reconciliation.application.prepare_booking import PrepareBooking
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.shared.domain.errors import InvariantViolation

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
POOL_A: PoolKey = ("bybit", "usdt-m", "USDT")
WINDOW_PAD_SECONDS = 300
MAX_SPAN_SECONDS = 7 * 24 * 3600  # 7 days, the probed limit
PROPOSAL_EXPIRY_SECONDS = 24 * 3600


# --- Fakes -------------------------------------------------------------------


class FakeDiscrepancyRepository:
    def __init__(self, discrepancies: Sequence[DiscrepancyRecord] = ()) -> None:
        self._discrepancies = list(discrepancies)
        self.list_calls: list[tuple] = []

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]:
        self.list_calls.append((pool, status, open_only))
        return list(self._discrepancies)

    async def upsert_open(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("PrepareBooking never writes discrepancy rows")

    async def resolve_absent(self, *args: object, **kwargs: object) -> int:
        raise NotImplementedError("PrepareBooking never writes discrepancy rows")


class FakeBookingProposalRepository:
    """Models the real repository's own idempotency
    (``ux_booking_proposals_pending_per_discrepancy``): a second ``insert``
    for a ``discrepancy_id`` that already holds one returns ``None`` rather
    than a second row (design.md § 3)."""

    def __init__(self) -> None:
        self.inserted: list[NewBookingProposal] = []
        self._pending_discrepancy_ids: set[UUID] = set()
        self.mark_state_calls: list[tuple] = []
        self._rejection_matches: dict[UUID, Observation] = {}

    def configure_matching_rejection(
        self, discrepancy_id: UUID, observation: Observation
    ) -> None:
        self._rejection_matches[discrepancy_id] = observation

    async def insert(self, proposal: NewBookingProposal) -> BookingProposalRecord | None:
        if proposal.discrepancy_id in self._pending_discrepancy_ids:
            return None
        self._pending_discrepancy_ids.add(proposal.discrepancy_id)
        self.inserted.append(proposal)
        return BookingProposalRecord(
            id=uuid4(),
            discrepancy_id=proposal.discrepancy_id,
            exchange=proposal.exchange,
            venue=proposal.venue,
            settlement_currency=proposal.settlement_currency,
            symbol=proposal.symbol,
            kind=proposal.kind,
            allocation_id=proposal.allocation_id,
            strategy_id=proposal.strategy_id,
            side=proposal.side,
            quantity=proposal.quantity,
            observed_venue_net_base=proposal.observed_venue_net_base,
            observed_ledger_net_base=proposal.observed_ledger_net_base,
            observed_allocation_ids=tuple(proposal.observed_allocation_ids),
            fills=tuple(proposal.fills),
            client_order_id=proposal.client_order_id,
            expires_at=proposal.expires_at,
            prepared_by_job_id=proposal.prepared_by_job_id,
            created_at=NOW,
            state="PENDING",
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            execution_attempt_id=None,
        )

    async def get_for_update(self, proposal_id: UUID) -> BookingProposalRecord:
        raise NotImplementedError("not exercised by PrepareBooking")

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
        self.mark_state_calls.append(
            (proposal_id, state, at, decided_by, decision_reason, execution_attempt_id)
        )
        return True

    async def list_pending(self, limit: int = 100) -> list[BookingProposalRecord]:
        return []

    async def has_matching_rejection(
        self, discrepancy_id: UUID, observation: Observation
    ) -> bool:
        configured = self._rejection_matches.get(discrepancy_id)
        return configured is not None and configured == observation

    async def expire_pending(self, now: datetime) -> int:
        return 0


class FakeVenueFillReader:
    def __init__(
        self, fills: Sequence[VenueFill] = (), raises: Exception | None = None
    ) -> None:
        self._fills = list(fills)
        self._raises = raises
        self.calls: list[tuple[PoolKey, str, datetime, datetime]] = []

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        self.calls.append((pool, symbol, start, end))
        if self._raises is not None:
            raise self._raises
        return list(self._fills)


class FakeVenueFillReaderRegistry:
    def __init__(self, readers: dict[tuple[str, str], FakeVenueFillReader]) -> None:
        self._readers = readers
        self.requested: list[tuple[str, str]] = []

    def for_pool(self, exchange: str, venue: str) -> FakeVenueFillReader:
        self.requested.append((exchange, venue))
        reader = self._readers.get((exchange, venue))
        if reader is None:
            raise LookupError(f"no venue fill reader registered for {exchange}/{venue}")
        return reader


class FakeRecordedFillIds:
    def __init__(self, recorded: frozenset[str] = frozenset()) -> None:
        self._recorded = recorded
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def recorded_fill_ids(
        self, exchange: str, venue: str, exchange_fill_ids: Sequence[str]
    ) -> frozenset[str]:
        self.calls.append((exchange, venue, tuple(exchange_fill_ids)))
        return frozenset(fid for fid in exchange_fill_ids if fid in self._recorded)


class FakeAllocationOwner:
    def __init__(self, owners: dict[UUID, UUID]) -> None:
        self._owners = owners

    async def strategy_for(self, allocation_id: UUID) -> UUID:
        return self._owners[allocation_id]


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


# --- Builders ------------------------------------------------------------


def _discrepancy(
    *,
    pool: PoolKey = POOL_A,
    symbol: str = "STXUSDT",
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    venue_net_base: Decimal = Decimal("0"),
    ledger_net_base: Decimal = Decimal("0.5"),
    open_allocation_ids: tuple[UUID, ...] = (),
    first_observed_at: datetime = NOW,
) -> DiscrepancyRecord:
    exchange, venue, settlement_currency = pool
    return DiscrepancyRecord(
        id=uuid4(),
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        kind=kind,
        venue_net_base=venue_net_base,
        ledger_net_base=ledger_net_base,
        open_allocation_ids=open_allocation_ids,
        consecutive_scans=3,
        status=DiscrepancyStatus.CONFIRMED,
        first_observed_at=first_observed_at,
        last_observed_at=first_observed_at,
        confirmed_at=first_observed_at,
        resolved_at=None,
        first_scan_id=uuid4(),
        last_scan_id=uuid4(),
        resolved_by_scan_id=None,
    )


def _fill(
    *,
    exchange_fill_id: str = "f1",
    exchange_order_id: str | None = "o1",
    symbol: str = "STXUSDT",
    side: str = "SELL",
    quantity: Decimal = Decimal("0.5"),
    price: Decimal = Decimal("2.5"),
    fee: Decimal = Decimal("0"),
    fee_currency: str = "USDT",
    filled_at: datetime = NOW,
) -> VenueFill:
    return VenueFill(
        exchange_fill_id=exchange_fill_id,
        exchange_order_id=exchange_order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        fee_currency=fee_currency,
        filled_at=filled_at,
    )


def _build(
    *,
    discrepancies: Sequence[DiscrepancyRecord] = (),
    venue_readers: dict[tuple[str, str], FakeVenueFillReader] | None = None,
    recorded: frozenset[str] = frozenset(),
    owners: dict[UUID, UUID] | None = None,
    dry_run: bool = False,
    window_pad_seconds: int = WINDOW_PAD_SECONDS,
    max_span_seconds: int = MAX_SPAN_SECONDS,
    proposal_expiry_seconds: int = PROPOSAL_EXPIRY_SECONDS,
) -> tuple[
    PrepareBooking,
    FakeDiscrepancyRepository,
    FakeBookingProposalRepository,
    FakeVenueFillReaderRegistry,
    FakeRecordedFillIds,
    SpyCommit,
]:
    discrepancy_repo = FakeDiscrepancyRepository(discrepancies)
    proposals = FakeBookingProposalRepository()
    registry = FakeVenueFillReaderRegistry(venue_readers or {})
    recorded_ids = FakeRecordedFillIds(recorded)
    allocation_owner: AllocationOwnerPort = FakeAllocationOwner(owners or {})
    commit = SpyCommit()
    use_case = PrepareBooking(
        discrepancies=discrepancy_repo,
        proposals=proposals,
        venue_fills=registry,
        recorded_fill_ids=recorded_ids,
        allocation_owner=allocation_owner,
        clock=FrozenClock(NOW),
        commit=commit,
        window_pad_seconds=window_pad_seconds,
        max_span_seconds=max_span_seconds,
        proposal_expiry_seconds=proposal_expiry_seconds,
        dry_run=dry_run,
    )
    return use_case, discrepancy_repo, proposals, registry, recorded_ids, commit


# --- Happy path ----------------------------------------------------------


async def test_a_confirmed_discrepancy_yields_a_prepared_proposal() -> None:
    allocation_id = uuid4()
    strategy_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, commit = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: strategy_id},
    )

    result = await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    proposal = proposals.inserted[0]
    assert proposal.discrepancy_id == discrepancy.id
    assert proposal.allocation_id == allocation_id
    assert proposal.strategy_id == strategy_id
    assert proposal.side == "SELL"
    assert proposal.quantity == Decimal("0.5")
    assert proposal.client_order_id == "vnu:bybit:fill:f1"
    assert result.proposals_prepared == 1
    assert commit.commits == 1


# --- Money-critical: unbookable kinds never proposed ----------------------


async def test_ambiguous_partial_reduce_and_no_matching_allocation_never_proposed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both unbookable verdicts are wired with fills that WOULD match and an
    allocation owner that WOULD resolve, so a bug that forgets the
    ``BOOKABLE_KINDS`` gate produces a visible extra proposal rather than
    failing some other way first."""
    allocation_id = uuid4()
    ambiguous = _discrepancy(
        kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE,
        open_allocation_ids=(allocation_id,),
    )
    no_match = _discrepancy(
        kind=DiscrepancyKind.NO_MATCHING_ALLOCATION,
        open_allocation_ids=(allocation_id,),
    )
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[ambiguous, no_match],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.sweep(uuid4())

    assert proposals.inserted == []
    assert result.proposals_prepared == 0


# --- Money-critical: prepare writes nothing beyond a PENDING proposal ------


async def test_prepare_writes_no_ledger_or_execution_rows() -> None:
    """``mark_state`` is the ONLY repository method that can ever attach an
    ``execution_attempt_id`` or move a proposal off ``PENDING`` (ports.py's
    own docstring). Asserting it is never called during ``sweep`` is the
    closest a fakes-only unit test gets to proving nothing reached the
    ledger or ``execution_attempts`` -- this use case's ports carry no
    reference to either table at all."""
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert proposals.mark_state_calls == []


# --- Idempotency: at most one PENDING proposal per discrepancy ------------


async def test_at_most_one_pending_proposal_per_discrepancy() -> None:
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    first = await use_case.sweep(uuid4())
    second = await use_case.sweep(uuid4())

    assert first.proposals_prepared == 1
    assert second.proposals_prepared == 0
    assert len(proposals.inserted) == 1


# --- Rejection suppression --------------------------------------------------


async def test_rejection_suppresses_identical_observation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )
    proposals.configure_matching_rejection(
        discrepancy.id,
        Observation(
            kind=discrepancy.kind,
            venue_net_base=discrepancy.venue_net_base,
            ledger_net_base=discrepancy.ledger_net_base,
        ),
    )

    with caplog.at_level(logging.DEBUG):
        result = await use_case.sweep(uuid4())

    assert proposals.inserted == []
    assert reader.calls == []
    assert result.proposals_suppressed == 1
    suppression_records = [r for r in caplog.records if "suppress" in r.message.lower()]
    assert suppression_records
    assert all(r.levelno <= logging.INFO for r in suppression_records)


async def test_moved_observation_gets_fresh_proposal_after_rejection() -> None:
    """A REJECTED proposal exists for this discrepancy, but the observation
    moved since -- ``has_matching_rejection`` answers ``False`` for the
    CURRENT triple, so a fresh proposal must still be prepared."""
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )
    # A rejection is on record, but for a DIFFERENT (now-stale) observation.
    proposals.configure_matching_rejection(
        discrepancy.id,
        Observation(
            kind=discrepancy.kind,
            venue_net_base=Decimal("99"),
            ledger_net_base=Decimal("99"),
        ),
    )

    result = await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert result.proposals_prepared == 1


# --- DRY_RUN hard skip -------------------------------------------------------


async def test_dry_run_hard_skip_no_fetch_no_proposal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, discrepancy_repo, proposals, _, _, commit = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
        dry_run=True,
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.sweep(uuid4())

    assert reader.calls == []
    assert proposals.inserted == []
    assert discrepancy_repo.list_calls == []
    assert commit.commits == 0
    assert result.proposals_prepared == 0
    dry_run_records = [r for r in caplog.records if "dry_run" in r.message.lower()]
    assert dry_run_records
    assert all(r.levelno == logging.WARNING for r in dry_run_records)


# --- Symbol spelling: the echoed fill symbol is validated, never trusted ----


async def test_a_fill_reported_under_a_different_contract_marker_is_accepted() -> None:
    """The venue echoes ``STXUSDT_PERP`` (Pionex's marker); the discrepancy
    is stored as ``STXUSDT.P`` (TradingView's). Both strip to the same
    market key, so this is accepted -- and the frozen proposal's ``symbol``
    is the MARKET KEY, never either raw spelling."""
    allocation_id = uuid4()
    discrepancy = _discrepancy(symbol="STXUSDT.P", open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill(symbol="STXUSDT_PERP")])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert proposals.inserted[0].symbol == "STXUSDT"


async def test_a_fill_from_a_genuinely_different_market_refuses_the_proposal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id = uuid4()
    discrepancy = _discrepancy(symbol="STXUSDT.P", open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill(symbol="ETHUSDT")])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.sweep(uuid4())

    assert proposals.inserted == []
    assert result.proposals_skipped == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "STXUSDT" in r.message and "ETHUSDT" in r.message and str(discrepancy.id) in r.message
        for r in warnings
    )


# --- Window span -------------------------------------------------------------


async def test_window_span_exactly_at_the_max_is_accepted() -> None:
    allocation_id = uuid4()
    first_observed_at = NOW - timedelta(seconds=MAX_SPAN_SECONDS - WINDOW_PAD_SECONDS)
    discrepancy = _discrepancy(
        open_allocation_ids=(allocation_id,), first_observed_at=first_observed_at
    )
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    result = await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert result.proposals_skipped == 0


async def test_window_span_over_the_max_by_one_second_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id = uuid4()
    first_observed_at = NOW - timedelta(seconds=MAX_SPAN_SECONDS - WINDOW_PAD_SECONDS + 1)
    discrepancy = _discrepancy(
        open_allocation_ids=(allocation_id,), first_observed_at=first_observed_at
    )
    reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.sweep(uuid4())

    assert proposals.inserted == []
    assert reader.calls == []  # refused BEFORE fetching -- never a truncated window
    assert result.proposals_skipped == 1
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# --- Venue fill read errors ---------------------------------------------------


async def test_a_venue_fill_read_error_skips_that_discrepancy_and_the_sweep_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id = uuid4()
    failing_pool: PoolKey = ("bybit", "usdt-m", "USDT")
    healthy_pool: PoolKey = ("binance", "usdt-m", "USDT")
    failing = _discrepancy(pool=failing_pool, open_allocation_ids=(allocation_id,))
    healthy = _discrepancy(pool=healthy_pool, open_allocation_ids=(allocation_id,))
    failing_reader = FakeVenueFillReader(raises=VenueFillReadError("bybit unreachable"))
    healthy_reader = FakeVenueFillReader([_fill()])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[failing, healthy],
        venue_readers={
            ("bybit", "usdt-m"): failing_reader,
            ("binance", "usdt-m"): healthy_reader,
        },
        owners={allocation_id: uuid4()},
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert proposals.inserted[0].discrepancy_id == healthy.id
    assert result.proposals_prepared == 1
    assert result.proposals_skipped == 1
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_a_registry_lookup_failure_for_an_unserved_pool_propagates() -> None:
    allocation_id = uuid4()
    discrepancy = _discrepancy(open_allocation_ids=(allocation_id,))
    use_case, _, proposals, _, _, commit = _build(
        discrepancies=[discrepancy],
        venue_readers={},  # nothing registered for bybit/usdt-m
        owners={allocation_id: uuid4()},
    )

    with pytest.raises(LookupError):
        await use_case.sweep(uuid4())

    assert proposals.inserted == []
    assert commit.commits == 0


# --- Settlement currency: the pool's own, never a constant --------------------


async def test_settlement_currency_passed_to_match_fills_is_the_pools_own_not_a_constant() -> (
    None
):
    """``fee_currency`` equals the pool's OWN settlement currency, so the fee
    must NOT be subtracted (design decision 5's rule). The quantity is
    chosen so the match only succeeds when that exact currency is what
    ``match_fills`` compares against -- any hardcoded or wrong currency would
    wrongly subtract the fee and produce ``SUM_MISMATCH`` instead."""
    allocation_id = uuid4()
    discrepancy = _discrepancy(
        open_allocation_ids=(allocation_id,),
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("1.0"),
    )
    reader = FakeVenueFillReader(
        [_fill(quantity=Decimal("1.0"), fee=Decimal("0.001"), fee_currency="USDT")]
    )
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    result = await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    assert result.proposals_prepared == 1


# --- PoolKey field order -------------------------------------------------------


async def test_pool_key_built_with_exchange_venue_currency_in_the_right_order() -> None:
    allocation_id = uuid4()
    pool: PoolKey = ("bybit", "usdt-m", "USDT")
    discrepancy = _discrepancy(pool=pool, open_allocation_ids=(allocation_id,))
    reader = FakeVenueFillReader([_fill()])
    use_case, _, _, registry, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    await use_case.sweep(uuid4())

    assert registry.requested == [("bybit", "usdt-m")]
    assert len(reader.calls) == 1
    called_pool, called_symbol, _, _ = reader.calls[0]
    assert called_pool == ("bybit", "usdt-m", "USDT")
    assert called_symbol == "STXUSDT"


# --- Mapping round-trip: no field dropped or swapped ---------------------------


async def test_venue_fill_maps_to_proposed_fill_snapshot_without_dropping_or_swapping_fields() -> (
    None
):
    allocation_id = uuid4()
    discrepancy = _discrepancy(
        open_allocation_ids=(allocation_id,),
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("0.7"),
    )
    fill = _fill(
        exchange_fill_id="unique-fill-id",
        exchange_order_id="unique-order-id",
        side="SELL",
        quantity=Decimal("0.7"),
        price=Decimal("3.33"),
        fee=Decimal("0.09"),
        fee_currency="USDT",
        filled_at=NOW - timedelta(minutes=5),
    )
    reader = FakeVenueFillReader([fill])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={allocation_id: uuid4()},
    )

    await use_case.sweep(uuid4())

    assert len(proposals.inserted) == 1
    (snapshot,) = proposals.inserted[0].fills
    assert snapshot.exchange_fill_id == fill.exchange_fill_id
    assert snapshot.exchange_order_id == fill.exchange_order_id
    assert snapshot.side == fill.side
    assert snapshot.quantity == fill.quantity
    assert snapshot.price == fill.price
    assert snapshot.fee == fill.fee
    assert snapshot.fee_currency == fill.fee_currency
    assert snapshot.filled_at == fill.filled_at


# --- No open allocation id on a bookable kind is a bug, not a refusal ---------


async def test_a_bookable_discrepancy_with_no_open_allocation_id_raises() -> None:
    discrepancy = _discrepancy(open_allocation_ids=())
    reader = FakeVenueFillReader([_fill()])
    use_case, _, _, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={},
    )

    with pytest.raises(InvariantViolation):
        await use_case.sweep(uuid4())


# --- Money-critical: a full close spread over several allocations -----------


async def test_full_close_over_several_allocations_is_refused_never_booked_to_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rung 2 fires for ANY number of open allocations: a flat venue closed
    all of them. Booking the whole close against the first allocation would
    drive it negative and leave the others open, a permanent corruption of
    an append-only ledger. Splitting it would need an invented FIFO or
    pro-rata rule, which the owner ruled out, so it is refused."""
    first, second = uuid4(), uuid4()
    discrepancy = _discrepancy(
        ledger_net_base=Decimal("0.5"), open_allocation_ids=(first, second)
    )
    reader = FakeVenueFillReader([_fill(quantity=Decimal("0.5"))])
    use_case, _, proposals, _, _, _ = _build(
        discrepancies=[discrepancy],
        venue_readers={("bybit", "usdt-m"): reader},
        owners={first: uuid4(), second: uuid4()},
    )

    with caplog.at_level(logging.WARNING):
        await use_case.sweep(uuid4())

    assert proposals.inserted == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        str(discrepancy.id) in r.getMessage() and "2 open allocations" in r.getMessage()
        for r in warnings
    )
