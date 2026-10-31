"""A seeded generator of ledger states, for T2 and T5 (design addendum "open
positions", section L).

``hypothesis`` is not a dependency of the backend, so this is the standard
library's ``random.Random`` with a FIXED seed: the same few hundred states on every
run, and a failure names the state's index.

A state is a few allocations and a few in-flight attempts. One allocation is a
sequence of fills built so that every shape the fold has to judge occurs: a
position held (long or short), a position closed in part, a position flat because
its fills cancel exactly, one flat only because a base-currency fee shrank its
purchase, a fee in the settlement currency, in the base currency and in a third
one, a market written under two or three spellings, fills of either origin, and
the odd symbol that cannot be split from the pool's currency.

Quantities are whole thousandths and prices whole units, so every sum is exact:
nothing here depends on rounding.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import InFlightAttemptOrigin, LedgerGroup
from strategy_manager.performance.domain.open_position import FillAggregate
from strategy_manager.shared.domain.mode import Mode
from tests.owner import OWNER_ID

SEED = 20261013
STATES = 300

_BUY = "BUY"
_SELL = "SELL"
_STEP = Decimal("0.001")
_EPOCH = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

SETTLEMENT = "USDT"
BASE = "SOL"
THIRD = "BNB"
# Three spellings of ONE market, and a symbol that cannot be split.
SPELLINGS = ("SOLUSDT.P", "SOLUSDT", "SOLUSDT_PERP")
UNSPLITTABLE = "XYZBTC"


@dataclass(frozen=True, slots=True)
class GeneratedFill:
    symbol: str
    side: str
    fee_currency: str
    rehearsal: bool
    quantity: Decimal
    notional: Decimal
    fee: Decimal
    filled_at: datetime


@dataclass(frozen=True, slots=True)
class GeneratedAllocation:
    allocation_id: UUID
    strategy_id: UUID
    strategy_name: str
    fills: tuple[GeneratedFill, ...]

    def ledger_groups(self) -> list[LedgerGroup]:
        """The rows the guard's reader folds."""
        return [
            LedgerGroup(
                allocation_id=self.allocation_id,
                user_id=OWNER_ID,
                mode=Mode.SIMULATION if fill.rehearsal else Mode.LIVE,
                strategy_name=self.strategy_name,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency=SETTLEMENT,
                symbol=fill.symbol,
                side=fill.side,
                fee_currency=fill.fee_currency,
                rehearsal=fill.rehearsal,
                quantity=fill.quantity,
                fee=fill.fee,
            )
            for fill in self.fills
        ]

    def aggregates(self) -> list[FillAggregate]:
        """The same fills, as the facts read answers them."""
        return [
            FillAggregate(
                allocation_id=self.allocation_id,
                strategy_id=self.strategy_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency=SETTLEMENT,
                symbol=fill.symbol,
                side=fill.side,
                fee_currency=fill.fee_currency,
                quantity=fill.quantity,
                notional=fill.notional,
                fee=fill.fee,
                first_filled_at=fill.filled_at,
                fill_count=1,
            )
            for fill in self.fills
        ]

    @property
    def resolves(self) -> bool:
        return all(fill.symbol != UNSPLITTABLE for fill in self.fills)


@dataclass(frozen=True, slots=True)
class GeneratedState:
    index: int
    allocations: tuple[GeneratedAllocation, ...]
    in_flight: tuple[InFlightAttemptOrigin, ...]

    def ledger_groups(self) -> list[LedgerGroup]:
        return [group for a in self.allocations for group in a.ledger_groups()]


def _uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def _split(rng: random.Random, units: int, parts: int) -> list[int]:
    """``units`` as ``parts`` positive integers (fewer when ``units`` is small)."""
    parts = max(1, min(parts, units))
    cuts = sorted(rng.sample(range(1, units), parts - 1)) if parts > 1 else []
    edges = [0, *cuts, units]
    return [edges[i + 1] - edges[i] for i in range(parts)]


def _fee(rng: random.Random, currency_pick: str, base_units: int) -> tuple[str, Decimal]:
    if currency_pick == "base":
        # Lower case on purpose: currencies are compared upper-cased.
        return BASE.lower(), Decimal(base_units) * _STEP
    if currency_pick == "third":
        return THIRD, Decimal(rng.randint(0, 4)) * _STEP
    return SETTLEMENT, Decimal(rng.randint(0, 30)) * _STEP


def _allocation(rng: random.Random, clock: list[datetime]) -> GeneratedAllocation:
    long = rng.random() < 0.7
    opening_side, closing_side = (_BUY, _SELL) if long else (_SELL, _BUY)

    held_units = rng.randint(2, 60)
    kind = rng.random()
    if kind < 0.25:
        closed_units, base_fee_units = held_units, 0  # a round trip: flat
    elif long and kind < 0.40:
        # Flat only because the base-currency fee shrank the purchase.
        closed_units = rng.randint(0, held_units - 1)
        base_fee_units = held_units - closed_units
    else:
        closed_units = rng.randint(0, held_units - 1)
        room = held_units - closed_units - 1 if long else 5
        base_fee_units = rng.randint(0, room)

    unsplittable = rng.random() < 0.06
    fills: list[GeneratedFill] = []
    base_fee_left = base_fee_units

    def add(side: str, units: int, price: Decimal) -> None:
        nonlocal base_fee_left
        pick = rng.choice(("settlement", "settlement", "third", "base"))
        take = 0
        if base_fee_left and pick == "base":
            take = base_fee_left
            base_fee_left = 0
        elif pick == "base":
            pick = "settlement"
        currency, fee = _fee(rng, pick, take)
        quantity = Decimal(units) * _STEP
        clock[0] += timedelta(minutes=rng.randint(1, 30))
        symbol = UNSPLITTABLE if unsplittable else rng.choice(SPELLINGS)
        fills.append(
            GeneratedFill(
                symbol=symbol,
                side=side,
                fee_currency=currency,
                rehearsal=rng.random() < 0.4,
                quantity=quantity,
                notional=quantity * price,
                fee=fee,
                filled_at=clock[0],
            )
        )

    for units in _split(rng, held_units, rng.randint(1, 3)):
        add(opening_side, units, Decimal(rng.randint(1, 400)))
    if closed_units:
        for units in _split(rng, closed_units, rng.randint(1, 2)):
            add(closing_side, units, Decimal(rng.randint(1, 400)))
    if base_fee_left:
        # No row took the base-currency fee: put it on a last row of the held side
        # with no quantity of its own is impossible, so add it to the first fill.
        first = fills[0]
        fills[0] = GeneratedFill(
            symbol=first.symbol,
            side=first.side,
            fee_currency=BASE.lower(),
            rehearsal=first.rehearsal,
            quantity=first.quantity,
            notional=first.notional,
            fee=first.fee + Decimal(base_fee_left) * _STEP
            if first.fee_currency.upper() == BASE
            else Decimal(base_fee_left) * _STEP,
            filled_at=first.filled_at,
        )

    return GeneratedAllocation(
        allocation_id=_uuid(rng),
        strategy_id=_uuid(rng),
        strategy_name=rng.choice(("Alpha", "Beta", "Gamma")),
        fills=tuple(fills),
    )


def _in_flight(rng: random.Random) -> InFlightAttemptOrigin:
    attempt_id = _uuid(rng)
    rehearsal = rng.random() < 0.5
    order_id = f"{REHEARSAL_ORDER_ID_PREFIX}{attempt_id}" if rehearsal else f"ORDER-{attempt_id}"
    return InFlightAttemptOrigin(
        attempt_id=attempt_id,
        mode=Mode.SIMULATION if rehearsal else Mode.LIVE,
        strategy_name=rng.choice(("Alpha", "Beta", "Gamma")),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency=SETTLEMENT,
        symbol=rng.choice(SPELLINGS),
        exchange_order_id=order_id,
    )


def generate_states(seed: int = SEED, count: int = STATES) -> list[GeneratedState]:
    rng = random.Random(seed)
    states: list[GeneratedState] = []
    for index in range(count):
        clock = [_EPOCH]
        allocations = tuple(_allocation(rng, clock) for _ in range(rng.randint(0, 4)))
        in_flight = tuple(_in_flight(rng) for _ in range(rng.randint(0, 3)))
        states.append(GeneratedState(index, allocations, in_flight))
    return states
