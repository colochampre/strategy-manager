"""``RegisterStrategy``: turning a TradingView signal into something this
system will act on.

**The id is not generated here, and that is the whole point.** A strategy's
id IS the ``signalType`` UUID that the TradingView alert carries in its body
(design.md § "strategy_id derives from signal_type" — a hard constraint).
The webhook receives an alert, reads ``signalType``, and looks up a strategy
under exactly that id. Generate an id here and no alert would ever match it.

So registering is really: "here is the UUID my alert already sends, and here
is what I want done when it arrives."

**A new strategy is DISABLED.** ``Strategy.enabled`` defaults to false and
this use case does not offer a way to override it. Registering and arming are
separate acts, because they answer different questions — "is this configured
correctly?" and "should it trade now?" — and only one of them moves money.
Enabling is an explicit second call.

**The pool is checked before the write.** The database's composite foreign key
already refuses a strategy on a pool that does not exist, but an integrity
error names a constraint rather than the mistake. Worse, the FK cannot see the
one case that matters most: a pool row that exists but is DISABLED. The
allocation engine reads only enabled pools, so such a strategy would register
cleanly, accept every signal, and size none of them.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.application.ports import (
    CommitPort,
    PoolCatalogPort,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)


class StrategyAlreadyRegistered(DomainError):
    """A strategy already exists under this id.

    Re-registering is refused rather than treated as an update, because the id
    comes from an alert the owner configured elsewhere: two different
    strategies arriving under one id means the alert is misconfigured, and
    silently overwriting would hide it.
    """


class PoolNotAvailable(DomainError):
    """No enabled capital pool matches this venue and settlement currency."""


@dataclass(frozen=True, slots=True)
class RegisterCommand:
    """``strategy_id`` is the alert's ``signalType``, supplied by the owner.

    ``allocation_percent`` is the share of the pool's BALANCE that a signal's
    ``requested`` amount is derived from — not of its availability. That was
    an explicit decision (see ``AllocationPercent``), and the distinction
    matters: what the strategy actually receives is then capped by what is
    genuinely available, which is where competing for free capital happens.
    """

    strategy_id: UUID
    name: str
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    allocation_percent: Decimal


class RegisterStrategy:
    """Registers a strategy against the pool it will draw capital from."""

    def __init__(
        self,
        repository: StrategyRepositoryPort,
        pools: PoolCatalogPort,
        commit: CommitPort,
    ) -> None:
        self._repository = repository
        self._pools = pools
        self._commit = commit

    async def register(self, command: RegisterCommand) -> Strategy:
        existing = await self._repository.get_by_id(command.strategy_id)
        if existing is not None:
            raise StrategyAlreadyRegistered(
                f"a strategy is already registered under id {command.strategy_id} "
                f"({existing.name!r}). That id comes from the alert's signalType, "
                "so two strategies sharing one means an alert is misconfigured."
            )

        await self._assert_pool_available(command)

        strategy = Strategy(
            id=command.strategy_id,
            name=command.name,
            policy=AllocationPolicy(
                venue=command.venue,
                settlement_currency=command.settlement_currency,
                fill_mode=command.fill_mode,
                allocation_percent=AllocationPercent(command.allocation_percent),
            ),
            # Registered, not armed. Enabling is a separate, deliberate call.
            enabled=False,
        )

        await self._repository.insert(strategy)
        await self._commit.commit()
        return strategy

    async def _assert_pool_available(self, command: RegisterCommand) -> None:
        available = await self._pools.enabled_pools()
        if (command.venue, command.settlement_currency) in available:
            return

        offered = ", ".join(f"{v.value}/{c.value}" for v, c in sorted(
            available, key=lambda pair: (pair[0].value, pair[1].value)
        ))
        raise PoolNotAvailable(
            f"no enabled capital pool for {command.venue.value}/"
            f"{command.settlement_currency.value}. Enabled pools are "
            f"{offered or 'none'}. A strategy on a disabled pool would accept "
            "every signal and size none of them."
        )
