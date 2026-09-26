"""AllowedPairs -- the set of ``market_key()``-normalized symbols a strategy
is permitted to open new positions on (design.md § 6 "Allowed pairs: an
array column, migration 0024"; spec: strategy-lifecycle § "Allowed-Pairs
List Per Strategy").

This VO only asserts the SHAPE of its entries: non-empty, upper-case, no
whitespace. Normalizing a raw signal symbol into that shape (``market_key()``)
is application work (``RegisterStrategy``, ``ReplaceAllowedPairs``), not this
VO's -- the same split ``AllocationPercent`` draws between "what a valid
value looks like" and "how one gets produced".
"""

from dataclasses import dataclass

from strategy_manager.shared.domain.errors import DomainError, InvariantViolation


class EmptyAllowedPairs(DomainError):
    """Raised by the APPLICATION layer (``RegisterStrategy``,
    ``ReplaceAllowedPairs``) when a request's allowed-pairs list is empty,
    or every entry normalizes to nothing (design.md § 6: "The >=1 rule is
    application-level ... not a DB CHECK, because seeded rows may
    legitimately be empty."). The VO itself does not raise this -- an empty
    ``AllowedPairs`` is a valid VALUE (a seeded strategy with no prior
    signals); only the REQUEST to end up with one is refused."""


@dataclass(frozen=True, slots=True)
class AllowedPairs:
    """Stored sorted (``.sorted()``), so the DB column and the API both
    render a stable order rather than a ``frozenset``'s arbitrary one."""

    pairs: frozenset[str]

    def __post_init__(self) -> None:
        for entry in self.pairs:
            if not entry:
                raise InvariantViolation("AllowedPairs entries must be non-empty")
            if entry != entry.upper():
                raise InvariantViolation(
                    f"AllowedPairs entry {entry!r} must be upper-case"
                )
            if any(character.isspace() for character in entry):
                raise InvariantViolation(
                    f"AllowedPairs entry {entry!r} must contain no whitespace"
                )

    def sorted(self) -> list[str]:
        return sorted(self.pairs)
