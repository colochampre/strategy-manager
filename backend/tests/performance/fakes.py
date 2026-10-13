"""In-memory stand-ins for ``performance`` ports."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import (
    OpenStateSourcePort,
    PoolFills,
    PositionFacts,
    SubmittedOrder,
)
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.open_position import DiscrepancyRow
from strategy_manager.performance.domain.operation import OperationFill, PricingFacts


class FakeFillsSource:
    """Returns whatever it was given for ANY pool it is asked about, so a test
    can hand ``ReadPoolPerformance`` a source that misbehaves (returns another
    pool's rows) and see the read refuse. Records each pool it was asked for."""

    def __init__(
        self,
        groups: list[FillGroup],
        rehearsal_fill_count: int = 0,
        rehearsal_by_strategy: dict[UUID, int] | None = None,
        rehearsal_groups: list[FillGroup] | None = None,
    ) -> None:
        self._groups = groups
        self._rehearsal_fill_count = rehearsal_fill_count
        self._rehearsal_by_strategy = tuple((rehearsal_by_strategy or {}).items())
        self._rehearsal_groups = tuple(rehearsal_groups or ())
        self.asked: list[PoolKey] = []

    async def pool_fills(self, pool: PoolKey) -> PoolFills:
        self.asked.append(pool)
        return PoolFills(
            tuple(self._groups),
            self._rehearsal_fill_count,
            self._rehearsal_by_strategy,
            self._rehearsal_groups,
        )


class FakePricingSource:
    """Answers the pricing facts it was given and records each call, so a test can
    count the calls and see which ids were asked for.

    ``default`` answers any id ``facts`` does not name; without one such an id
    is absent from the answer, as a source with no row for it would leave it."""

    def __init__(
        self,
        facts: Mapping[UUID, PricingFacts] | None = None,
        *,
        default: PricingFacts | None = None,
    ) -> None:
        self._facts = dict(facts or {})
        self._default = default
        self.calls: list[tuple[PoolKey, UUID, list[UUID]]] = []

    async def pricing_facts(
        self, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]:
        self.calls.append((pool, strategy_id, list(allocation_ids)))
        answer: dict[UUID, PricingFacts] = {}
        for allocation_id in allocation_ids:
            if allocation_id in self._facts:
                answer[allocation_id] = self._facts[allocation_id]
            elif self._default is not None:
                answer[allocation_id] = self._default
        return answer


class FakeOperationFillsSource:
    """Holds the fills of the operations it was given, keyed by
    ``(strategy_id, allocation_id)``, and answers at most ``limit`` of them.

    An operation it does not hold answers nothing, exactly as a source whose
    statement carries both predicates would. Every call is recorded, so a test
    can see the limit asked for and that both ids travelled together."""

    def __init__(self, held: Mapping[tuple[UUID, UUID], Sequence[OperationFill]]) -> None:
        self._held = {key: list(fills) for key, fills in held.items()}
        self.calls: list[tuple[UUID, UUID, int]] = []

    async def operation_fills(
        self, strategy_id: UUID, allocation_id: UUID, limit: int
    ) -> Sequence[OperationFill]:
        self.calls.append((strategy_id, allocation_id, limit))
        return self._held.get((strategy_id, allocation_id), [])[:limit]


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeOpenStateReader:
    """The guard's reader as a case table: it holds the two sequences it is told
    to hold and answers them unchanged, whoever asks. The SAME instance can be
    given to ``find_mismatches``' callers and to ``ReadOpenPositions``.

    ``calls`` is where the call order is recorded; hand several fakes ONE list
    and the order of statements across them is visible."""

    def __init__(
        self,
        opened: Sequence[OpenAllocationOrigin] = (),
        in_flight: Sequence[InFlightAttemptOrigin] = (),
        *,
        calls: list[str] | None = None,
    ) -> None:
        self._opened = tuple(opened)
        self._in_flight = tuple(in_flight)
        self.calls: list[str] = calls if calls is not None else []

    async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
        self.calls.append("open")
        return self._opened

    async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
        self.calls.append("in_flight")
        return self._in_flight


class FakeFactsSource:
    """The facts read as a table: ``facts`` by allocation id, ``submitted`` as
    the submitted-orders read. An id it holds nothing for is absent from the
    answer, as a source with no row for it would leave it."""

    def __init__(
        self,
        facts: Mapping[UUID, PositionFacts] | None = None,
        submitted: Sequence[SubmittedOrder] = (),
        *,
        calls: list[str] | None = None,
    ) -> None:
        self._facts = dict(facts or {})
        self._submitted = tuple(submitted)
        self.calls: list[str] = calls if calls is not None else []
        self.asked_ids: list[list[UUID]] = []

    async def position_facts(self, allocation_ids: Sequence[UUID]) -> Mapping[UUID, PositionFacts]:
        self.calls.append("facts")
        self.asked_ids.append(list(allocation_ids))
        return {i: self._facts[i] for i in allocation_ids if i in self._facts}

    async def submitted_orders(self) -> Sequence[SubmittedOrder]:
        self.calls.append("submitted")
        return self._submitted


class FakeDisagreementSource:
    """The confirmed-disagreement read as a table of rows."""

    def __init__(
        self, rows: Sequence[DiscrepancyRow] = (), *, calls: list[str] | None = None
    ) -> None:
        self._rows = tuple(rows)
        self.calls: list[str] = calls if calls is not None else []

    async def confirmed_open(self) -> Sequence[DiscrepancyRow]:
        self.calls.append("disagreements")
        return self._rows


class HeldOpenStateSource:
    """The held-read harness of rule R13: wraps the REAL open-state reader and
    parks the read between its first statement (the in-flight read) and its
    second (the open-allocations read).

    ``first_done`` is set once the first statement has returned; the second does
    not start until the test sets ``release``. Both are events the test controls,
    so ordering is proven by what the test does between them, never by a sleep."""

    def __init__(self, inner: OpenStateSourcePort) -> None:
        self._inner = inner
        self.first_done = asyncio.Event()
        self.release = asyncio.Event()

    async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
        answer = await self._inner.in_flight_attempts()
        self.first_done.set()
        return answer

    async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
        await self.release.wait()
        return await self._inner.open_allocations()
