"""Strategy aggregate: a registered TradingView strategy with a target
capital pool and a fill policy (design.md § strategies/domain/strategy.py).

No framework imports, per the layering rule that ``domain`` never depends on
FastAPI, SQLAlchemy or httpx.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs
from strategy_manager.strategies.domain.description import description_of


class FillMode(StrEnum):
    """Mirrors the ``strategies.fill_mode`` CHECK constraint."""

    SKIP = "SKIP"
    PARTIAL = "PARTIAL"


class Visibility(StrEnum):
    """Mirrors the ``strategies.visibility`` CHECK constraint (decisions 21 and 41).

    PUBLIC is on Explore. LINK and PRIVATE are off it: LINK takes whoever holds its
    link, PRIVATE whoever holds a live invitation code. A change of visibility keeps
    the subscribers a strategy has, so nothing here reaches the signal fan-out."""

    PUBLIC = "PUBLIC"
    LINK = "LINK"
    PRIVATE = "PRIVATE"


class Entry(StrEnum):
    """How someone other than the author arrives at a strategy: by nothing but its
    id, by its link, or with a live code made for it. The caller has checked the
    link or the code against this strategy before saying so."""

    NONE = "NONE"
    LINK = "LINK"
    CODE = "CODE"


def offered_to(visibility: Visibility, *, author_named: bool, entry: Entry) -> bool:
    """Whether someone other than the author may read this strategy's page and
    subscribe to it, arriving by ``entry`` (decision 41). PUBLIC takes anyone, LINK
    the holder of its link, PRIVATE the holder of a live code. A live code opens a
    LINK strategy too: it was made for this strategy, and the link would let the same
    person in. Nothing is offered while the author has no name (decision 27).

    A live seat reads its page whatever the visibility; that is the public read's
    own rule, in SQL (tasks.md J.1), as is ``archived_at``."""
    if not author_named:
        return False
    if visibility is Visibility.PUBLIC:
        return True
    if visibility is Visibility.LINK:
        return entry in (Entry.LINK, Entry.CODE)
    return entry is Entry.CODE


@dataclass(frozen=True, slots=True)
class AllocationPercent:
    """The strategy's share of its pool's BALANCE (not availability) that
    ``requested`` is derived from — the owner's explicit decision
    2026-08-18, superseding an earlier "percentage of availability" draft
    (design.md § "Order size never comes from the alert"; tasks.md 7.1).
    Mirrors the ``subscriptions.allocation_percent`` CHECK constraint:
    ``0 < value <= 100``.
    """

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise InvariantViolation("AllocationPercent.value must be a Decimal")
        if not (Decimal("0") < self.value <= Decimal("100")):
            raise InvariantViolation(
                "AllocationPercent.value must satisfy 0 < value <= 100"
            )


@dataclass(frozen=True, slots=True)
class AllocationPolicy:
    """The pool a strategy targets and how it behaves under partial
    availability. Extracted as a VO because these fields are always
    read and validated together — they are the strategy's whole allocation
    policy (design.md's ``strategies`` table columns).

    The share is not here: it belongs to a subscription (migration ``0033``)."""

    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode


@dataclass(frozen=True, slots=True)
class Strategy:
    """A registered strategy. ``id`` MUST equal the ``signal_type`` UUID the
    owner already pastes into TradingView (design.md § "strategy_id derives
    from signal_type" — HARD CONSTRAINT ON SLICE 3) — it is never generated
    by this object or by persistence.

    ``author_id`` is the ``User`` who registered it (multi-user design AD2). A
    strategy names a market, not a pool, so the author is not the owner of the
    money a signal moves: until subscriptions exist (PR C) it is, because a
    signal is worked in its author's pools."""

    id: UUID
    name: str
    policy: AllocationPolicy
    author_id: UUID
    enabled: bool = False
    visibility: Visibility = Visibility.PRIVATE
    allowed_pairs: AllowedPairs = AllowedPairs(frozenset())
    description: str | None = None
    archived_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise InvariantViolation("Strategy.name must be non-empty")
        # Held only in its stored shape: what ``description_of`` makes of it is
        # itself. A blank or padded one is turned into that shape before it gets
        # here, never written as it came.
        if self.description is not None and description_of(self.description) != self.description:
            raise InvariantViolation("Strategy.description must be trimmed and non-empty")
