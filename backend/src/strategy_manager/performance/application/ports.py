"""Ports owned by ``performance``. The consumer owns the port; the
infrastructure adapter implements it (same direction as ``FillRecorderPort``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.open_position import (
    DiscrepancyRow,
    FillAggregate,
    InFlightAttemptElement,
    OpenAllocationElement,
    PoolLabel,
    StrategyPage,
)
from strategy_manager.performance.domain.operation import OperationFill, PricingFacts
from strategy_manager.performance.domain.public_capital import LiveSeat
from strategy_manager.strategies.domain.enablement import EnablementEvent


@dataclass(frozen=True, slots=True)
class PoolFills:
    """Everything the ledger says about ONE pool.

    ``groups`` are the non-rehearsal aggregates: the only set any total reads.
    ``rehearsal_groups`` are the DRY_RUN aggregates, kept apart so that no
    figure can include them by accident; the trades list is their one reader,
    and only when it is asked for them. ``rehearsal_fill_count`` is how many
    DRY_RUN fills the scope holds, so a figure that ignores them can still say
    how many it ignored.
    """

    groups: tuple[FillGroup, ...]
    rehearsal_fill_count: int
    rehearsal_by_strategy: tuple[tuple[UUID, int], ...] = ()
    rehearsal_groups: tuple[FillGroup, ...] = ()

    def rehearsal_for(self, strategy_id: UUID) -> int:
        """How many rehearsal fills of ONE strategy the source left out. A
        strategy's report states its own count, never the pool's."""
        return sum(count for sid, count in self.rehearsal_by_strategy if sid == strategy_id)


class AllocationFillsSourcePort(Protocol):
    """Reads a pool's ledger as per-(allocation, strategy, side, fee currency)
    aggregates.

    Takes exactly one ``PoolKey``. There is no method that reads more than one
    pool, so a cross-pool total (CLAUDE.md rule 7) cannot be requested through
    this port.
    """

    async def pool_fills(self, user_id: UUID, pool: PoolKey) -> PoolFills: ...


class OperationFillsSourcePort(Protocol):
    """The individual fills of ONE operation (one allocation), oldest first.

    Takes the strategy AND the allocation, never the allocation alone, so a read
    without the strategy predicate cannot be requested through this port: an
    allocation of another strategy answers nothing. It answers at most ``limit``
    fills and applies no pool predicate on purpose; the caller refuses a fill of
    another pool after the read instead of silently losing it in a WHERE.
    """

    async def operation_fills(
        self, user_id: UUID, strategy_id: UUID, allocation_id: UUID, limit: int
    ) -> Sequence[OperationFill]: ...


class RehearsalPricingSourcePort(Protocol):
    """What the ledger and the signals say about how rehearsal operations were
    priced: for the allocations asked, in ONE call, the price each one's alert
    carried and the price range of each side's fills.

    An allocation the source holds no facts for is simply absent from the answer;
    the caller decides what that means. Takes the strategy as well as the ids, so
    another strategy's allocation is never answered through this strategy's read.
    """

    async def pricing_facts(
        self, user_id: UUID, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]: ...


class OpenStateSourcePort(Protocol):
    """The mode guard's own two reads, in the order the open positions read
    issues them (design addendum "open positions", section C, steps 1 and 2),
    restricted here to ONE user's rows (multi-user design AD8). Implemented by
    ``SqlAlchemyModeOriginReader``, whose ``user_id`` is optional: the worker's
    startup guard asks without it and reads the whole system."""

    async def in_flight_attempts(self, user_id: UUID) -> Sequence[InFlightAttemptElement]: ...

    async def open_allocations(self, user_id: UUID) -> Sequence[OpenAllocationElement]: ...


@dataclass(frozen=True, slots=True)
class PositionFacts:
    """What the facts read says about ONE open allocation: the reservation (its
    strategy, grant, status, pool and the opening attempt's leverage) and every
    group of the allocation's fills. Built from the two statements of
    ``position_facts`` (design section C)."""

    allocation_id: UUID
    strategy_id: UUID
    strategy_name: str
    strategy_archived: bool
    strategy_page: StrategyPage | None
    margin_granted: Decimal
    reservation_status: str
    leverage: Decimal | None
    reservation_pool: PoolLabel
    groups: tuple[FillAggregate, ...]


@dataclass(frozen=True, slots=True)
class SubmittedOrder:
    """One ``SUBMITTED`` attempt, with or without an order id. The parent
    columns are ``None`` when the LEFT joins found no reservation or strategy:
    no attempt is dropped by a missing parent."""

    attempt_id: UUID
    opening: bool
    pool: PoolLabel
    symbol: str
    exchange_order_id: str | None
    created_at: datetime
    strategy_id: UUID | None
    strategy_name: str | None
    strategy_archived: bool | None
    reservation_pool: PoolLabel | None


class OpenPositionFactsSourcePort(Protocol):
    """The facts the guard's reader does not carry. Each method is ONE statement
    group, never one per row; an allocation it knows nothing about is absent from
    ``position_facts``' answer, and the caller keeps its row."""

    async def position_facts(
        self, user_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PositionFacts]: ...

    async def submitted_orders(self, user_id: UUID) -> Sequence[SubmittedOrder]: ...


class ConfirmedDisagreementSourcePort(Protocol):
    """The open ``CONFIRMED`` rows of the reconciliation's discrepancies, read
    once. It reads no venue and writes nothing."""

    async def confirmed_open(self, user_id: UUID) -> Sequence[DiscrepancyRow]: ...


@dataclass(frozen=True, slots=True)
class PublicListing:
    """What anyone may read of a strategy on the public list. It is the whole of
    what leaves the strategy and author rows: no id of the author, no e-mail, no
    secret and no setting."""

    strategy_id: UUID
    name: str
    author_name: str
    exchange: str
    venue: str
    settlement_currency: str
    created_at: datetime
    # Whether the author has it taking signals now (tasks.md L.1).
    enabled: bool
    # Every ACTIVE seat, the author's included, live or not: the count the author's
    # own list shows (tasks.md F.5 and L.1).
    subscribers: int
    # The author's own words, written for anyone reading the strategy (decision 38).
    description: str | None = None


@dataclass(frozen=True, slots=True)
class PageEntry:
    """What a reader brings to a strategy off the list, besides a seat (decision 41):
    the link they followed, and whether a live code of THIS strategy was checked for
    them (``CheckInviteCode``). The source opens a LINK strategy to its current token,
    and a LINK or PRIVATE one to a checked code; neither opens anything else."""

    link: str | None = field(default=None, repr=False)
    code_checked: bool = False


NO_ENTRY = PageEntry()


class PublicStrategiesSourcePort(Protocol):
    """The one read that crosses users on purpose (tasks.md F.4). ``listings``
    answers only strategies on the public list: ``PUBLIC``, not archived, with a
    named author.

    ``listing`` is the one method that takes a user, the reader, and only to open
    one more page: a strategy turned private still answers to a reader who holds a
    live seat on it and is not its author (tasks.md J.1, decision 21), so the seat
    keeps the page where its share, leverage and Leave are. Any other strategy off
    the list is absent from it, so a caller cannot reach one by its id.

    Each method is ONE statement however many strategies it is asked about. A
    strategy with no real fill of its author or no seat is absent from those two
    answers.
    """

    async def listings(self) -> Sequence[PublicListing]: ...

    async def listing(
        self, strategy_id: UUID, reader_id: UUID, entry: PageEntry = NO_ENTRY
    ) -> PublicListing | None: ...

    async def author_fills(
        self, strategy_ids: Sequence[UUID]
    ) -> Mapping[UUID, Sequence[FillGroup]]:
        """Each strategy's real fills by its own author, folded per allocation as
        ``AllocationFillsSourcePort`` folds them. No rehearsal fill, and no fill
        of anyone else."""
        ...

    async def live_seats(
        self, strategy_ids: Sequence[UUID]
    ) -> Mapping[UUID, Sequence[LiveSeat]]: ...

    async def enablement(
        self, strategy_ids: Sequence[UUID]
    ) -> Mapping[UUID, Sequence[EnablementEvent]]:
        """Each strategy's enablement log, oldest first: the days active a card shows
        beside the age (tasks.md L.1). Only when it was on and off leaves."""
        ...
