"""Whether what the ledger holds agrees with the mode that opened it (owner
decision 28, multi-user design AD7).

A reservation records its mode, and its order, settle and close follow that
record. So a record that disagrees with the fills sends the close to the wrong
side: a rehearsal position closed against a live venue finds nothing to close,
and -- the dangerous direction -- a live position closed against the fake
exchange is booked flat in the ledger while it stays open at the venue.

This module is the pure decision. It reads nothing and logs nothing: the
adapter that reads the ledger and the use case that logs and refuses sit
outside it.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.market_symbol import base_currency_of
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode

_ZERO = Decimal(0)
_BUY = "BUY"

#: Joins the spellings of one allocation's symbol in ``OpenAllocationOrigin``.
SPELLING_SEPARATOR = " / "


class Origin(StrEnum):
    REHEARSAL = "rehearsal"
    LIVE = "live"
    MIXED = "mixed"


#: The only origin each recorded mode agrees with.
_ORIGIN_OF = {Mode.LIVE: Origin.LIVE, Mode.SIMULATION: Origin.REHEARSAL}


class Kind(StrEnum):
    POSITION = "position"
    ORDER = "order"


@dataclass(frozen=True, slots=True)
class LedgerGroup:
    """One aggregate row of the ledger: everything one allocation did on one
    side, in one fee currency, with fills of one origin."""

    allocation_id: UUID
    user_id: UUID
    mode: Mode
    strategy_name: str
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    side: str
    fee_currency: str
    rehearsal: bool
    quantity: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class OpenAllocationOrigin:
    allocation_id: UUID
    user_id: UUID
    mode: Mode
    strategy_name: str
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    holds_rehearsal_fill: bool
    holds_live_fill: bool


@dataclass(frozen=True, slots=True)
class InFlightAttemptOrigin:
    """A non-terminal execution attempt whose order the exchange already
    accepted (``exchange_order_id`` is recorded). ``mode`` is what its
    reservation recorded."""

    attempt_id: UUID
    mode: Mode
    strategy_name: str
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    exchange_order_id: str

    @property
    def rehearsal(self) -> bool:
        return self.exchange_order_id.startswith(REHEARSAL_ORDER_ID_PREFIX)


@dataclass(frozen=True, slots=True)
class ModeMismatch:
    """One thing the ledger holds that disagrees with its recorded mode."""

    kind: Kind
    origin: Origin
    recorded: Mode
    identifier: UUID
    strategy_name: str
    pool: str
    symbol: str


@dataclass(frozen=True, slots=True)
class UnclosableAllocations:
    """How many real allocations ``user_id`` holds open on ``exchange`` with no
    active trade-capable key there: nothing can close them (AD7)."""

    user_id: UUID
    exchange: str
    allocations: int


def fold_open_allocations(groups: Sequence[LedgerGroup]) -> tuple[OpenAllocationOrigin, ...]:
    """Every allocation whose net base quantity is not exactly zero, with the
    origin of the fills it holds.

    The rule is ``derive_trade``'s and ``net_base_quantity``'s: BUY adds, any
    other side subtracts, and a fee charged in the BASE currency subtracts
    because that much of a purchase never arrived. There is no tolerance -- a
    remainder however small is a position still held. Grouped by allocation,
    never by symbol, so an open under one spelling and a close under another
    are one flat allocation.

    A symbol whose base currency cannot be split from the pool's settlement
    currency makes the base-fee rule inapplicable. Such an allocation is
    reported as open rather than assumed flat: a guard that guesses 'closed'
    is the one that lets a real position through.
    """
    by_allocation: dict[UUID, list[LedgerGroup]] = defaultdict(list)
    for group in groups:
        by_allocation[group.allocation_id].append(group)

    opened: list[OpenAllocationOrigin] = []
    for allocation_id, rows in by_allocation.items():
        if _is_flat(rows):
            continue
        first = rows[0]
        opened.append(
            OpenAllocationOrigin(
                allocation_id=allocation_id,
                user_id=first.user_id,
                mode=first.mode,
                strategy_name=first.strategy_name,
                exchange=first.exchange,
                venue=first.venue,
                settlement_currency=first.settlement_currency,
                symbol=SPELLING_SEPARATOR.join(sorted({row.symbol for row in rows})),
                holds_rehearsal_fill=any(row.rehearsal for row in rows),
                holds_live_fill=any(not row.rehearsal for row in rows),
            )
        )
    return tuple(opened)


def _is_flat(rows: Sequence[LedgerGroup]) -> bool:
    net_base = _ZERO
    for row in rows:
        net_base += row.quantity if row.side == _BUY else -row.quantity
        try:
            base = base_currency_of(row.symbol, row.settlement_currency).upper()
        except InvariantViolation:
            return False
        if row.fee_currency.upper() == base:
            net_base -= row.fee
    return net_base == _ZERO


def find_mismatches(
    *,
    open_allocations: Sequence[OpenAllocationOrigin],
    in_flight: Sequence[InFlightAttemptOrigin],
) -> tuple[ModeMismatch, ...]:
    """What disagrees with the mode its reservation recorded.

    The brake has no say: since decision 14 a real position closes for real
    under it, so ``DRY_RUN`` no longer tells which side a position belongs to.
    A reservation recorded ``LIVE`` cannot close anything a rehearsal touched,
    nor one recorded ``SIMULATION`` anything a live fill touched. An allocation
    holding both kinds disagrees whatever it recorded: no single exchange can
    close it. An in-flight order is judged by the exchange order id the fake
    minted.
    """
    found: list[ModeMismatch] = []

    for allocation in open_allocations:
        if allocation.holds_rehearsal_fill and allocation.holds_live_fill:
            origin = Origin.MIXED
        elif allocation.holds_rehearsal_fill:
            origin = Origin.REHEARSAL
        else:
            origin = Origin.LIVE
        if origin is _ORIGIN_OF[allocation.mode]:
            continue
        found.append(
            ModeMismatch(
                kind=Kind.POSITION,
                origin=origin,
                recorded=allocation.mode,
                identifier=allocation.allocation_id,
                strategy_name=allocation.strategy_name,
                pool=_pool_label(
                    allocation.exchange, allocation.venue, allocation.settlement_currency
                ),
                symbol=allocation.symbol,
            )
        )

    for attempt in in_flight:
        origin = Origin.REHEARSAL if attempt.rehearsal else Origin.LIVE
        if origin is _ORIGIN_OF[attempt.mode]:
            continue
        found.append(
            ModeMismatch(
                kind=Kind.ORDER,
                origin=origin,
                recorded=attempt.mode,
                identifier=attempt.attempt_id,
                strategy_name=attempt.strategy_name,
                pool=_pool_label(attempt.exchange, attempt.venue, attempt.settlement_currency),
                symbol=attempt.symbol,
            )
        )

    return tuple(
        sorted(
            found,
            key=lambda m: (
                m.kind is Kind.ORDER,
                m.strategy_name,
                m.pool,
                m.symbol,
                str(m.identifier),
            ),
        )
    )


def find_unclosable(
    *,
    open_allocations: Sequence[OpenAllocationOrigin],
    trade_capable: Collection[tuple[UUID, str]],
) -> tuple[UnclosableAllocations, ...]:
    """The real open allocations whose user holds no active trade-capable key on
    their exchange, counted per user and exchange (AD7). By the recorded mode:
    that is what sends the close to the venue, whatever the fills say."""
    unkeyed = Counter(
        (allocation.user_id, allocation.exchange)
        for allocation in open_allocations
        if allocation.mode is Mode.LIVE
        and (allocation.user_id, allocation.exchange) not in trade_capable
    )
    return tuple(
        UnclosableAllocations(user_id=user_id, exchange=exchange, allocations=count)
        for (user_id, exchange), count in sorted(
            unkeyed.items(), key=lambda item: (str(item[0][0]), item[0][1])
        )
    )


def _pool_label(exchange: str, venue: str, settlement_currency: str) -> str:
    return f"{exchange}/{venue}/{settlement_currency}"


def describe_refusal(
    *,
    mismatches: Sequence[ModeMismatch],
    unclosable: Sequence[UnclosableAllocations],
) -> str:
    """The one ERROR an operator reads: every offender, and the way out."""
    lines: list[str] = []
    if mismatches:
        lines.append(
            f"Refusing to start: {len(mismatches)} item(s) in the ledger disagree "
            "with the mode their reservation recorded:"
        )
        lines.extend(f"  - {_describe(mismatch)}" for mismatch in mismatches)
        lines.append(
            "The way out: check each one against the venue by hand. A close and a "
            "settle follow the recorded mode, so they would go to the wrong side: a "
            "real position closed on the simulated side would read flat in the "
            "ledger and still be open on the venue."
        )
    if unclosable:
        lines.append(
            f"Refusing to start: {sum(item.allocations for item in unclosable)} real "
            "open allocation(s) belong to a user with no active trade-capable key "
            "on their exchange:"
        )
        lines.extend(
            f"  - user {item.user_id}: {item.allocations} allocation(s) on {item.exchange}"
            for item in unclosable
        )
        lines.append(
            "The way out: the user stores a trade-capable key on that exchange. "
            "Without one, nothing can close these positions."
        )
    return "\n".join(lines)


def _describe(mismatch: ModeMismatch) -> str:
    where = (
        f"strategy '{mismatch.strategy_name}', pool {mismatch.pool}, "
        f"symbol {mismatch.symbol}"
    )
    recorded = mismatch.recorded.value
    if mismatch.kind is Kind.ORDER:
        return (
            f"order: {where}, execution attempt {mismatch.identifier} recorded "
            f"{recorded} ({mismatch.origin.value} order not yet settled)"
        )
    if mismatch.origin is Origin.MIXED:
        return (
            f"position: {where}, allocation {mismatch.identifier} recorded {recorded} "
            "and holds both rehearsal and live fills; no side can close it safely"
        )
    return (
        f"position: {where}, allocation {mismatch.identifier} recorded {recorded} "
        f"(opened by {mismatch.origin.value} fills)"
    )
