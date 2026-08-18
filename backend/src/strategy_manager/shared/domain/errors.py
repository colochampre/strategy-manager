"""Domain-layer errors shared across every module.

Kept deliberately small: individual modules define their own specific error
subclasses where a distinct branch of business logic needs one.
"""


class DomainError(Exception):
    """Base class for all domain-layer errors across modules."""


class InvariantViolation(DomainError):
    """Raised when a domain invariant is violated (e.g. currency mismatch)."""
