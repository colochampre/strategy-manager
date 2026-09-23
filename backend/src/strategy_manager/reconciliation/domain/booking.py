"""Booking domain: matching venue-reported fills against an observed delta,
and the deterministic client order id a matched booking is recorded under --
never submitted: a VENUE attempt is constructed already FILLED
(design.md's component inventory § reconciliation/domain/booking.py; design
decisions 4, 5, 13).

No framework imports, no I/O, no clock: mirrors ``classify.py``'s pure
``Decimal``-only shape exactly. This module MUST NOT import ``market_key``
(or anything from ``execution.domain.market_symbol``) -- every symbol
reaching this module has already been normalised by its caller (design
decision 13; ``match_fills``/``build_client_order_id`` never see a symbol at
all, only fill ids and quantities).
"""

from collections.abc import Sequence, Set
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.shared.domain.errors import InvariantViolation

_ZERO = Decimal("0")

BOOKABLE_KINDS: frozenset[DiscrepancyKind] = frozenset(
    {
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    }
)
"""The only two verdicts a booking proposal may ever be prepared for
(design.md § 14): ``AMBIGUOUS_PARTIAL_REDUCE`` has no single allocation to
attribute a close to, and ``NO_MATCHING_ALLOCATION`` has no allocation at
all. Mirrors ``ck_booking_proposals_kind`` (migration ``0023``) -- the
database is the real guard; this constant is what a caller (``PrepareBooking``,
Unit 4b) checks BEFORE ever building a ``NewBookingProposal``, so an
unbookable kind never reaches the repository."""


class BookingState(StrEnum):
    """Mirrors ``booking_proposals.state``'s CHECK constraint (migration
    ``0023``, design.md § 3) exactly -- the same relationship
    ``DiscrepancyStatus`` already has to its own CHECK."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ProposedFill:
    """One venue-reported fill, exactly as this pure module needs it to
    match and to build a client order id.

    Identical in shape to
    ``reconciliation.application.ports.ProposedFillSnapshot`` -- this
    ``domain`` module cannot import that type (it lives in ``application``,
    and CLAUDE.md's layering rule is that ``domain`` imports no framework
    and nothing from a layer above it), so it declares its own copy here.
    The caller (``PrepareBooking``, Unit 4b) maps ``VenueFill``/
    ``ProposedFillSnapshot`` instances into this type, and maps a
    ``MatchedBooking``'s fills back into ``ProposedFillSnapshot`` for the
    frozen JSONB write.
    """

    exchange_fill_id: str
    exchange_order_id: str | None
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime
    """Tz-aware UTC, same convention as ``VenueFill.filled_at``."""


def _canonical_sort_key(fill: ProposedFill) -> tuple[datetime, tuple[int, str]]:
    """design.md § 3, "The frozen snapshot's exact shape": ``(filled_at ASC,
    exchange_fill_id ASC)`` with the tiebreak comparing ids as ``(len(id),
    id)``. This equals numeric order for Binance's integer trade ids
    (``"9" < "10"`` is FALSE as a plain string compare; ``(1, "9") <
    (2, "10")`` is TRUE) and stays a TOTAL order for Bybit's opaque
    ``execId`` strings, which carry no numeric guarantee of their own.
    """

    return (fill.filled_at, (len(fill.exchange_fill_id), fill.exchange_fill_id))


def canonical_order(fills: Sequence[ProposedFill]) -> tuple[ProposedFill, ...]:
    """The one canonical ordering this whole slice agrees on: the frozen
    ``fills`` JSONB snapshot's order (design.md § 3), the order
    ``build_client_order_id`` searches for the earliest fill, and the order
    ``match_fills`` returns its matched fills in."""

    return tuple(sorted(fills, key=_canonical_sort_key))


class MatchRefusalReason(StrEnum):
    """Design decision 5's refusal conditions, named so a caller's log line
    (and any future metric) can key on the reason without parsing free
    text."""

    ZERO_UNRECORDED = "ZERO_UNRECORDED"
    NONPOSITIVE_QUANTITY = "NONPOSITIVE_QUANTITY"
    MIXED_SIDES = "MIXED_SIDES"
    SUM_MISMATCH = "SUM_MISMATCH"


@dataclass(frozen=True, slots=True)
class MatchRefused:
    """A typed refusal, never an exception: design decision 5 says a
    proposal simply does not get written, with a WARNING -- the caller
    (``PrepareBooking``, Unit 4b) logs ``reason``/``detail`` and moves on to
    the next discrepancy. Nothing here raises, and nothing here returns an
    empty success silently -- every refusal is this explicit, inspectable
    type, never swallowed."""

    reason: MatchRefusalReason
    detail: str


@dataclass(frozen=True, slots=True)
class MatchedBooking:
    """The unrecorded fills matched a discrepancy's observed delta exactly.
    ``fills`` is already in canonical order (design.md § 3) -- the same
    order the frozen ``fills`` JSONB snapshot must be written in -- and
    ``side`` is the single side every one of them shares."""

    fills: tuple[ProposedFill, ...]
    side: str


def match_fills(
    delta_base: Decimal,
    fills: Sequence[ProposedFill],
    already_recorded_ids: Set[str],
    settlement_currency: str,
) -> MatchedBooking | MatchRefused:
    """design.md § 5, "The match rule".

    ``fills`` is every venue-reported fill fetched for the window. This
    function first drops whichever ones ``already_recorded_ids`` (keyed by
    ``exchange_fill_id``, NEVER symbol -- design.md § 13) says the ledger
    already holds, then requires the survivors' SIGNED, fee-adjusted sum to
    equal ``delta_base`` exactly, by ``Decimal`` value: BUY contributes
    ``+quantity``, SELL contributes ``-quantity``.

    ``settlement_currency`` drives the IDENTICAL fee rule
    ``ReadSymbolPositions``/``SqlAlchemyLedgerRepository
    .net_positions_by_symbol`` already applies (design decision 5): a fill's
    ``fee`` is subtracted from its own signed contribution only when its
    ``fee_currency`` differs from ``settlement_currency`` (compared
    case-insensitively, mirroring that same repository's
    ``func.upper(...) != settlement_currency.upper()``) -- provably a no-op
    on USDⓈ-M, where every fee lands in the settlement currency, and
    load-bearing the day a non-USDT-settled pool books a close.

    **Binding decision, flagged for the orchestrator to confirm**: design.md
    § 5's own prose names this function's signature as ``match_fills
    (delta_base, fills, already_recorded_ids)`` -- three parameters, no
    ``settlement_currency``. That same section requires the identical
    ``ReadSymbolPositions`` fee rule, which cannot be evaluated without
    knowing the pool's settlement currency; the orchestrator's own binding
    instructions for this unit separately require proving the fee rule a
    no-op for USDT-settled fills. ``settlement_currency`` is therefore added
    as a fourth, required parameter rather than silently applying no fee
    rule at all (which would produce a false ``SUM_MISMATCH`` refusal on
    every fee-in-base-currency close) or reaching into a settings singleton
    from a module that must stay pure and dependency-free.

    Refuses -- never raises, never proposes on an empty match -- when: no
    fill survives the ``already_recorded_ids`` filter (``ZERO_UNRECORDED``);
    any surviving fill's ``quantity`` is not strictly positive
    (``NONPOSITIVE_QUANTITY``); the surviving fills mix ``'BUY'``/``'SELL'``
    (``MIXED_SIDES``); or the signed, fee-adjusted sum does not equal
    ``delta_base`` exactly (``SUM_MISMATCH``). A set of unrecorded fills all
    sitting on the side that CONTRADICTS ``delta_base``'s own sign (e.g. all
    BUY against a negative delta) is not a separate rule -- a sum of
    same-signed contributions can never equal an oppositely-signed delta, so
    that case surfaces as ``SUM_MISMATCH`` too.
    """

    unrecorded = [fill for fill in fills if fill.exchange_fill_id not in already_recorded_ids]
    ordered = canonical_order(unrecorded)

    if not ordered:
        return MatchRefused(MatchRefusalReason.ZERO_UNRECORDED, "no unrecorded fills to match")

    for fill in ordered:
        if fill.quantity <= _ZERO:
            return MatchRefused(
                MatchRefusalReason.NONPOSITIVE_QUANTITY,
                f"fill {fill.exchange_fill_id!r} quantity {fill.quantity} is not positive",
            )

    sides = {fill.side for fill in ordered}
    if len(sides) > 1:
        return MatchRefused(
            MatchRefusalReason.MIXED_SIDES,
            f"unrecorded fills mix sides: {sorted(sides)!r}",
        )

    settlement = settlement_currency.upper()
    total = _ZERO
    for fill in ordered:
        signed_quantity = fill.quantity if fill.side == "BUY" else -fill.quantity
        fee_adjustment = fill.fee if fill.fee_currency.upper() != settlement else _ZERO
        total += signed_quantity - fee_adjustment

    if total != delta_base:
        return MatchRefused(
            MatchRefusalReason.SUM_MISMATCH,
            f"unrecorded sum {total} != observed delta {delta_base}",
        )

    return MatchedBooking(fills=ordered, side=ordered[0].side)


def build_client_order_id(exchange: str, fills: Sequence[ProposedFill]) -> str:
    """``vnu:{exchange}:fill:{earliest_exchange_fill_id}`` under the
    canonical ordering, ALWAYS -- deliberately not the venue's order id,
    which design decision 4 originally proposed.

    Keyed on the order id, one venue order filling across two scans (a
    limit close filled in pieces, a staged liquidation) yields two bookings
    sharing one ``client_order_id``: the second approval collides with the
    unique constraint and is read as a harmless replay -- SUPERSEDED, zero
    writes, that close never bookable. A fill is recorded at most once
    (``ux_ledger_exchange_fill``), so the earliest unrecorded fill names
    exactly one booking, and a replayed approval of the SAME proposal still
    collides, because the id is frozen at prepare. The order ids are not
    lost: every fill in the frozen snapshot, and every ledger row, keeps its
    own ``exchange_order_id``.

    ``exchange`` is embedded so two venues issuing the same fill id cannot
    collide (0019's reason for widening ``ux_ledger_exchange_fill``), and the
    ``:`` is outside Bybit's order-link alphabet, so a VENUE attempt can
    never be submitted by accident.

    Raises ``InvariantViolation`` on an empty ``fills`` sequence: there is no
    earliest fill, and building an id for zero fills is a bug in the caller.
    """

    ordered = canonical_order(fills)
    if not ordered:
        raise InvariantViolation("cannot build a client order id from zero fills")
    return f"vnu:{exchange}:fill:{ordered[0].exchange_fill_id}"
