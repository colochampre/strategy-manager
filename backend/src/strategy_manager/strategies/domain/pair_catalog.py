"""Which pairs a strategy may list on a capital pool (decision 41).

The rule is deliberately tiny: a venue lists a set of pairs, a request names
some, and the difference is what the venue does not list. Everything that
makes it hard (reading a venue, caching, the HTTP mapping) lives outside this
module, which imports no framework.

All four errors are siblings under ``DomainError``, never subclasses of one
another: a handler written for one must not swallow a different one. In
particular an unreadable venue is not an unknown pair, and a pool nobody can
read a catalogue for is not an unreadable venue.
"""

from collections.abc import Collection

from strategy_manager.shared.domain.errors import DomainError


class UnknownPairs(DomainError):
    """The venue does not list these pairs for the pool.

    ``unknown`` is a sorted tuple in ``market_key`` form, so the symbols a
    refusal names are stable and identical to what a save accepts back.
    """

    def __init__(self, unknown: Collection[str]) -> None:
        self.unknown: tuple[str, ...] = tuple(sorted(unknown))
        super().__init__(f"the venue does not list: {', '.join(self.unknown)}")


class PairCatalogUnavailable(DomainError):
    """The venue's catalogue could not be read, or what it returned could not
    be trusted. Fail closed: nothing is accepted on the strength of it."""


class PairCatalogNotServed(DomainError):
    """No catalogue source exists for this pool's exchange and venue.

    Not an empty catalogue: an empty answer would read as "this venue lists
    nothing". There is no fallback, which is the failure being prevented.
    """


class PairsChangedConcurrently(DomainError):
    """The stored pair list changed between the unvalidated read and the row
    lock, so a pair that was never checked would now be an addition."""


def unknown_pairs(candidates: Collection[str], available: Collection[str]) -> tuple[str, ...]:
    """Candidates the venue does not list, sorted. Both sides are expected in
    ``market_key`` form; this rule only compares."""
    return tuple(sorted(set(candidates) - set(available)))
