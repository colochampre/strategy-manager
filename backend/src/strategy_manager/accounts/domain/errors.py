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
