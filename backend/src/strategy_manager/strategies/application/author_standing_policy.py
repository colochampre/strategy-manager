"""``AuthorStandingPolicy``: fills ``StrategyPolicySnapshot.author_suspended``
(public-site LS9, PS.13 S4).

A suspended author's strategies stop opening for EVERY subscriber, and their closes keep
running. The fact lives on the author's user row, not on the strategy, and the strategy is
deliberately NOT disabled: the sweep closes at market whatever sits on a disabled strategy
(``stopped_positions_reader._STOPPED``), which would sell the subscribers' positions.

It wraps whichever ``StrategyPolicyPort`` a composition root already has, so both reads of
the policy see it: ``ProcessDelivery``'s, before the lock, and ``AllocateCapital``'s, in
it. The snapshot's field defaults to ``False``, which makes a root that forgets to wrap its
port fail silently; ``tests/signals/infrastructure/test_suspension_integration.py`` goes
through ``main``'s own composition for that reason.
"""

from dataclasses import replace
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.application.ports import (
    StrategyPolicyPort,
    StrategyPolicySnapshot,
)


class AuthorStandingPort(Protocol):
    async def is_suspended(self, user_id: UUID) -> bool:
        """Whether the admin suspended the account. A plain read, never a row lock: the
        policy is read before the pool's advisory lock too, and a row lock there would
        invert the order (pool lock first, row locks after)."""
        ...


class AuthorStandingPolicy:
    """Implements ``allocation.application.StrategyPolicyPort``."""

    def __init__(self, inner: StrategyPolicyPort, standing: AuthorStandingPort) -> None:
        self._inner = inner
        self._standing = standing

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        policy = await self._inner.policy_for(strategy_id)
        return replace(policy, author_suspended=await self._standing.is_suspended(policy.author_id))
