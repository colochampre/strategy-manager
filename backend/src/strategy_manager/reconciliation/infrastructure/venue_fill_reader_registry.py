"""Which reader serves a given pool's venue fill-window read.

Mirrors ``venue_position_reader_registry.VenuePositionReaderRegistry``
exactly, including its refusal rule: a pool nothing serves RAISES here
rather than falling back to any reader. There is no sensible default — the
whole point of a registry keyed by ``(exchange, venue)`` is that "which
reader answers for this pool" has exactly one answer, and a fallback would
silently answer a different pool's question.

The exception raised here (``UnservedFillPoolError``) is deliberately NOT
``VenueFillReadError``. A booking sweep swallows only the latter — a live
venue call that failed THIS sweep, tried again next time. A pool with no
registered reader at all is a configuration or programming error, and must
propagate loud enough to kill the job, exactly like
``VenuePositionReaderRegistry`` already behaves on the position-read side.
"""

from collections.abc import Iterable, Mapping

from strategy_manager.reconciliation.application.ports import VenueFillReaderPort
from strategy_manager.shared.domain.errors import DomainError

PoolRoute = tuple[str, str]
"""``(exchange, venue)`` — what selects a reader."""


class UnservedFillPoolError(DomainError):
    """No registered reader serves this pool's fill window. Never swallowed
    by a booking sweep."""


class VenueFillReaderRegistry:
    """Implements ``VenueFillReaderRegistryPort`` over a fixed set of
    readers."""

    def __init__(self, readers: Iterable[VenueFillReaderPort]) -> None:
        by_pool: dict[PoolRoute, VenueFillReaderPort] = {}
        for reader in readers:
            for venue in reader.venues:
                route = (reader.exchange, venue)
                existing = by_pool.get(route)
                if existing is not None:
                    raise UnservedFillPoolError(
                        f"pool {route[0]}/{route[1]} is claimed by both "
                        f"{type(existing).__name__} and {type(reader).__name__}; "
                        "exactly one reader must serve each pool"
                    )
                by_pool[route] = reader
        self._by_pool = by_pool

    @property
    def pools(self) -> frozenset[PoolRoute]:
        return frozenset(self._by_pool)

    @property
    def readers(self) -> Mapping[PoolRoute, VenueFillReaderPort]:
        """Read-only view, for composition and for tests that assert wiring."""
        return dict(self._by_pool)

    def for_pool(self, exchange: str, venue: str) -> VenueFillReaderPort:
        reader = self._by_pool.get((exchange, venue))
        if reader is None:
            served = ", ".join(f"{e}/{v}" for e, v in sorted(self._by_pool))
            raise UnservedFillPoolError(
                f"no venue fill reader serves pool {exchange}/{venue}; "
                f"registered pools are {served or 'none'}"
            )
        return reader
