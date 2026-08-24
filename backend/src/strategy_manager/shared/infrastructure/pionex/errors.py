"""Errors raised by the Pionex adapters.

These are infrastructure failures, not domain errors: they describe a remote
system misbehaving, so they deliberately do not inherit from ``DomainError``.
"""


class PionexError(Exception):
    """Base class for every Pionex adapter failure."""


class PionexApiError(PionexError):
    """Pionex was reachable but did not return a usable result.

    Covers transport failures, non-200 statuses, ``result: false`` envelopes
    and payloads that do not match the documented shape. The caller cannot
    tell these apart in a way that changes its behaviour — every one of them
    means "this call did not happen".
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class PionexOrderNotFound(PionexError):
    """Pionex answered the lookup and said it has no such order.

    Kept distinct from ``PionexApiError`` because the two lead to opposite
    decisions and only one of them is safe to get wrong. "No such order" means
    the order never reached the exchange, so the reservation holding capital
    for it must be released. "The call failed" means we do not know, so the
    only safe move is to ask again.

    Misreading a failed call as "no such order" releases capital backing a
    position that is really open — the system forgets a live trade. Misreading
    "no such order" as a failed call retries until a human looks. Only ever
    raise this on a signal Pionex actually gave.
    """
