"""Domain errors owned by ``accounts``."""

from strategy_manager.shared.domain.errors import DomainError


class StaleBalanceSnapshot(DomainError):
    """The last balance the exchange reported is too old to size a trade on.

    This is deliberately a distinct error rather than a generic invariant
    violation, because it does not mean the code is wrong -- it means the
    system stopped knowing how much capital exists. The only safe response is
    to refuse to allocate.

    A missed trade costs an opportunity. A trade sized against a balance that
    no longer exists costs capital. When the sync job dies, those are the two
    outcomes on offer, and the choice is not close.
    """


class KeyRejected(DomainError):
    """The venue refused the key itself: unknown key, wrong secret or signature,
    expired, or (on Binance) a wrong source IP or a missing permission.

    Reported distinctly from ``VenueUnreachable``: a rejected key is the
    owner's to fix, an unreachable venue is worth retrying. The message never
    carries a payload or a secret, only the venue's own error code.
    """


class VenueUnreachable(DomainError):
    """The key could not be checked because the venue did not answer in a
    usable way: a transport failure, a timeout, a 5xx, or a body that is not
    the documented shape. Nothing is known about the key."""
