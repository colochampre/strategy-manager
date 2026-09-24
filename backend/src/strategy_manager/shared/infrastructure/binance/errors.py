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


class BinanceRuleRefusal(BinanceApiError):
    """The venue evaluated a specific per-symbol rule and the order fails it:
    not a perpetual, not trading, below the minimum quantity, above the
    market ceiling, or below the minimum notional
    (``PerpContract.assert_tradable``).

    Kept distinct from a plain ``BinanceApiError`` so the futures adapter can
    translate EXACTLY this -- a rule the venue's own catalogue enforces -- into
    ``execution.application.ports.OrderNotPlaceable``, without also catching a
    leverage or instrument read that failed for an unrelated reason (network,
    auth, a 5xx). Still a ``BinanceApiError`` itself, so any caller that only
    knows the wider vocabulary keeps working unchanged.
    """


class BinanceOrderNotFound(BinanceError):
    """Binance answered the lookup and said it has no such order.

    Kept distinct from ``BinanceApiError`` for the reason its Bybit and Pionex
    twins spell out: "no such order" means the order never reached the
    exchange, so the capital behind it must be released, while "the call
    failed" means we do not know and must ask again. Misreading the second as
    the first makes this system forget a live position.

    Only ``-2013`` produces this. ``-1001`` and ``-1007`` describe a request
    Binance may well have executed, and they stay ``BinanceApiError``.
    """
