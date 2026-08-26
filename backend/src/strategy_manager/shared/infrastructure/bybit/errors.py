"""Errors raised by the Bybit adapters.

Infrastructure failures, not domain errors: they describe a remote system
misbehaving, so they deliberately do not inherit from ``DomainError``. Mirrors
``pionex/errors.py`` on purpose — the execution layer already knows how to
tell a definitive rejection from an unknown outcome, and that logic should not
have to learn a second vocabulary per venue.
"""


class BybitError(Exception):
    """Base class for every Bybit adapter failure."""


class BybitApiError(BybitError):
    """Bybit was reachable but did not return a usable result.

    Covers transport failures, non-200 statuses, non-zero ``retCode``
    envelopes and payloads that do not match the documented shape.

    ``code`` carries Bybit's ``retCode``. It is what separates "the exchange
    decided" from "we do not know", and that distinction is what decides
    whether reserved capital is released or held.
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


class BybitOrderNotFound(BybitError):
    """Bybit answered the lookup and said it has no such order.

    Kept distinct from ``BybitApiError`` for the reason its Pionex twin
    spells out at length: "no such order" means the order never reached the
    exchange, so the capital behind it must be released, while "the call
    failed" means we do not know and must ask again. Misreading the second as
    the first makes this system forget a live position.
    """
