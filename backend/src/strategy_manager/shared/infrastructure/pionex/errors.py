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
    means "this balance read did not happen".
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
