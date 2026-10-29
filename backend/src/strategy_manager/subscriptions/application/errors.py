"""Why a subscription request is refused. The router maps each to its status."""

from strategy_manager.shared.domain.errors import DomainError


class StrategyNotFound(DomainError):
    """No strategy is registered under this id."""


class StrategyArchived(DomainError):
    """Archive is terminal (decision 14): nobody subscribes to an archived strategy."""


class NoPoolForMarket(DomainError):
    """The user holds no pool for the strategy's market. A subscription sits in the
    subscriber's own pool, so without one there is nothing to size it from."""


class AlreadySubscribed(DomainError):
    """The user already holds a live (ACTIVE or LEAVING) subscription to this strategy.
    A user who comes back after leaving gets a new one only once the old one ENDED."""


class SubscriptionNotFound(DomainError):
    """No subscription of THIS user under this id. Another user's subscription is
    indistinguishable from a missing one (multi-user design AD8)."""


class SubscriptionNotActive(DomainError):
    """Leaving and changing the share are for an ACTIVE subscription only."""


class AuthorCannotLeave(DomainError):
    """An author stays subscribed to their own strategy (owner decision 22). The way
    out is to disable it, which stops it for everyone, or to archive it, which ends
    every subscription."""
