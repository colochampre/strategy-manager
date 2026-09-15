"""Errors raised by the Binance adapters.

Infrastructure failures, not domain errors. Mirrors ``bybit/errors.py`` so the
execution layer keeps one vocabulary for "the exchange decided" versus "we do
not know".
"""


class BinanceError(Exception):
    """Base class for every Binance adapter failure."""


class BinanceApiError(BinanceError):
    """Binance was reachable but did not return a usable result.

    Unlike Bybit and Pionex, Binance reports a rejection through the HTTP
    status with a ``{"code": <negative>, "msg": ...}`` body, not inside a 200
    envelope. ``code`` carries that negative number; ``http_status`` the
    status line.
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
