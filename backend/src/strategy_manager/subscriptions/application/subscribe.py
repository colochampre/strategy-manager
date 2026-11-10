"""``Subscribe``: a user takes a place in a strategy, in their own pool.

**How someone other than the author gets in** (decisions 21, 27 and 41): a PUBLIC
strategy takes anyone, a LINK one whoever brings its current token, a PRIVATE one
whoever brings a live code made for it, and a live code opens a LINK one too. The
link is tried before the code, and the code is read only when nothing else opens the
strategy, so a code is spent only when it is what let its holder in.

**A code is spent with the seat**, in this one transaction: the seat is written,
then the code is marked redeemed by it under the code's row lock, re-read there, so
two holders of one code make one seat. A code that is no longer live by then
refuses the seat, which the caller rolls back.

**The log answers who got in with a code** (K.D advisory A3): a spend that loses
to another, or finds the code gone, says so at WARNING; a seat a code paid for, at
INFO once committed. Each names the user, the strategy and the seat, never the code.
"""

import logging
from uuid import UUID, uuid4

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.leverage import Leverage
from strategy_manager.strategies.domain.invite_code import InviteCode, InviteCodeNotLive
from strategy_manager.strategies.domain.share_token import link_opens
from strategy_manager.strategies.domain.strategy import AllocationPercent, Entry, offered_to
from strategy_manager.subscriptions.application.errors import (
    AlreadySubscribed,
    NoPoolForMarket,
    StrategyArchived,
    StrategyNotFound,
)
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    InviteCodeCheckPort,
    InviteCodeSpendPort,
    StrategyLookupPort,
    StrategyMarket,
    SubscriptionRepositoryPort,
    UserPoolPort,
)
from strategy_manager.subscriptions.domain.subscription import Subscription

logger = logging.getLogger(__name__)


class Subscribe:
    def __init__(
        self,
        subscriptions: SubscriptionRepositoryPort,
        strategies: StrategyLookupPort,
        pools: UserPoolPort,
        commit: CommitPort,
        clock: ClockPort,
        codes: InviteCodeCheckPort,
        spend: InviteCodeSpendPort,
    ) -> None:
        self._subscriptions = subscriptions
        self._strategies = strategies
        self._pools = pools
        self._commit = commit
        self._clock = clock
        self._codes = codes
        self._spend = spend

    async def subscribe(
        self,
        user_id: UUID,
        strategy_id: UUID,
        allocation_percent: AllocationPercent,
        leverage: Leverage,
        *,
        link: str | None = None,
        code: str | None = None,
    ) -> Subscription:
        """Raises ``StrategyNotFound``, ``StrategyArchived``, ``NoPoolForMarket`` or
        ``AlreadySubscribed``, each before anything is written. The last one is
        also what the repository raises when a concurrent request wins the race
        the ``has_live`` read cannot close. A code may also raise
        ``TooManyCodeAttempts`` or ``InviteCodeNotLive``; the second after the seat
        was written, when the code went in the meantime."""
        strategy = await self._strategies.find(strategy_id)
        # Another author's strategy that is not offered to what the user brings is
        # answered exactly as one that does not exist (decision 21, G.2): the same
        # error, so the answer does not tell them apart.
        if strategy is None:
            raise StrategyNotFound(f"no strategy registered under id {strategy_id}")
        spent = None
        if strategy.author_id != user_id:
            spent = await self._entered_with(strategy, user_id, link, code)
        if strategy.archived:
            raise StrategyArchived(f"strategy {strategy_id} is archived")

        pool_id = await self._pools.pool_id(user_id, strategy.market)
        if pool_id is None:
            raise NoPoolForMarket(
                f"you hold no pool on {'/'.join(strategy.market)}, which this strategy trades"
            )

        if await self._subscriptions.has_live(user_id, strategy_id):
            raise AlreadySubscribed(f"you are already subscribed to strategy {strategy_id}")

        now = self._clock.now()
        subscription = Subscription(
            id=uuid4(),
            user_id=user_id,
            strategy_id=strategy_id,
            pool_id=pool_id,
            allocation_percent=allocation_percent,
            leverage=leverage,
            created_at=now,
        )
        await self._subscriptions.insert(subscription)
        if spent is not None:
            gone = await self._spend.spend(strategy_id, spent, user_id, subscription.id, now)
            if gone is not None:
                logger.warning(
                    "invite code no longer live at its spend, seat refused: user=%s "
                    "strategy=%s outcome=%s",
                    user_id,
                    strategy_id,
                    gone.value,
                )
                raise InviteCodeNotLive(gone)
        await self._commit.commit()
        if spent is not None:
            logger.info(
                "invite code redeemed: user=%s strategy=%s subscription=%s",
                user_id,
                strategy_id,
                subscription.id,
            )
        return subscription

    async def _entered_with(
        self, strategy: StrategyMarket, user_id: UUID, link: str | None, code: str | None
    ) -> InviteCode | None:
        """The code to spend, when a code is what lets ``user_id`` in; None when the
        strategy opens to them without one. Raises ``StrategyNotFound`` when nothing
        they bring opens it."""
        by_link = Entry.LINK if link_opens(strategy.share_token, link) else Entry.NONE
        named = strategy.author_named
        if offered_to(strategy.visibility, author_named=named, entry=by_link):
            return None
        checked = None
        if code is not None and offered_to(
            strategy.visibility, author_named=named, entry=Entry.CODE
        ):
            checked = await self._codes.check(user_id, strategy.id, code)
        if checked is None:
            raise StrategyNotFound(f"no strategy registered under id {strategy.id}")
        return checked
