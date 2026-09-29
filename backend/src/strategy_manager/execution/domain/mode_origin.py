"""Which mode a piece of ledger state belongs to (owner decision 28).

``DRY_RUN`` is configuration read at startup. Flipping it with a position
still open sends that position's close to the wrong exchange: a rehearsal
position closed against a live venue finds nothing to close, and -- the
dangerous direction -- a live position closed against the fake exchange is
booked flat in the ledger while it stays open at the venue.

This module is the pure decision. It reads nothing and logs nothing: the
adapter that reads the ledger and the use case that logs and refuses sit
outside it.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.market_symbol import base_currency_of
from strategy_manager.shared.domain.errors import InvariantViolation

_ZERO = Decimal(0)
_BUY = "BUY"


class Origin(StrEnum):
    REHEARSAL = "rehearsal"
    LIVE = "live"
    MIXED = "mixed"


class Kind(StrEnum):
    POSITION = "position"
    ORDER = "order"


@dataclass(frozen=True, slots=True)
class LedgerGroup:
    """One aggregate row of the ledger: everything one allocation did on one
    side, in one fee currency, with fills of one origin."""

    allocation_id: UUID
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
    accepted (``exchange_order_id`` is recorded)."""

    attempt_id: UUID
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
    """One thing the ledger holds that the configured mode cannot close."""

    kind: Kind
    origin: Origin
    identifier: UUID
    strategy_name: str
    pool: str
    symbol: str


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
                strategy_name=first.strategy_name,
                exchange=first.exchange,
                venue=first.venue,
                settlement_currency=first.settlement_currency,
                symbol=" / ".join(sorted({row.symbol for row in rows})),
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
    dry_run: bool,
    open_allocations: Sequence[OpenAllocationOrigin],
    in_flight: Sequence[InFlightAttemptOrigin],
) -> tuple[ModeMismatch, ...]:
    """What the configured mode cannot safely close.

    ``DRY_RUN=false`` cannot close anything a rehearsal touched, and
    ``DRY_RUN=true`` cannot close anything a live fill touched. An allocation
    holding both kinds is refused in either mode: no single exchange can close
    it. An in-flight order is judged by the exchange order id the fake minted.
    """
    found: list[ModeMismatch] = []

    for allocation in open_allocations:
        offends = allocation.holds_live_fill if dry_run else allocation.holds_rehearsal_fill
        if not offends:
            continue
        if allocation.holds_rehearsal_fill and allocation.holds_live_fill:
            origin = Origin.MIXED
        elif allocation.holds_rehearsal_fill:
            origin = Origin.REHEARSAL
        else:
            origin = Origin.LIVE
        found.append(
            ModeMismatch(
                kind=Kind.POSITION,
                origin=origin,
                identifier=allocation.allocation_id,
                strategy_name=allocation.strategy_name,
                pool=_pool_label(
                    allocation.exchange, allocation.venue, allocation.settlement_currency
                ),
                symbol=allocation.symbol,
            )
        )

    for attempt in in_flight:
        if attempt.rehearsal == dry_run:
            continue
        found.append(
            ModeMismatch(
                kind=Kind.ORDER,
                origin=Origin.REHEARSAL if attempt.rehearsal else Origin.LIVE,
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


def _pool_label(exchange: str, venue: str, settlement_currency: str) -> str:
    return f"{exchange}/{venue}/{settlement_currency}"


def describe_refusal(*, dry_run: bool, mismatches: Sequence[ModeMismatch]) -> str:
    """The one ERROR an operator reads: every offender, and the way out."""
    mode = "true" if dry_run else "false"
    other = "live" if dry_run else "rehearsal"
    lines = [
        f"Refusing to start: DRY_RUN is {mode}, but {len(mismatches)} item(s) in the "
        f"ledger belong to the other mode ({other}):"
    ]
    for mismatch in mismatches:
        lines.append(f"  - {_describe(mismatch)}")

    lines.append(
        "The way out: close each position in the mode that opened it "
        "(DRY_RUN=true for a rehearsal position, DRY_RUN=false for a live one) "
        "and let each in-flight order settle in that mode, then flip DRY_RUN."
    )
    if dry_run:
        lines.append(
            "Do not close a live position with DRY_RUN=true: the close would go "
            "to the fake exchange, the ledger would show it flat, and the real "
            "position would still be open on the venue."
        )
    return "\n".join(lines)


def _describe(mismatch: ModeMismatch) -> str:
    where = (
        f"strategy '{mismatch.strategy_name}', pool {mismatch.pool}, "
        f"symbol {mismatch.symbol}"
    )
    if mismatch.kind is Kind.ORDER:
        return (
            f"order: {where}, execution attempt {mismatch.identifier} "
            f"({mismatch.origin.value} order not yet settled)"
        )
    if mismatch.origin is Origin.MIXED:
        return (
            f"position: {where}, allocation {mismatch.identifier} holds both "
            "rehearsal and live fills; neither mode can close it safely, so "
            "check it against the venue by hand"
        )
    return (
        f"position: {where}, allocation {mismatch.identifier} "
        f"(opened by {mismatch.origin.value} fills)"
    )
