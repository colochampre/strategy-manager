"""Keeps the HTTP client's per-request INFO lines out of this system's logs.

``httpx`` logs one INFO line per request and renders the full URL. Binance
signs in the QUERY STRING, so that line carries ``timestamp`` and ``signature``.
The signature is timestamp-bound and the API key travels in a header, so it is
noise rather than a live leak, but it is noise that holds a credential's
derivative and has no reason to exist. In the worker it also drowned the log an
operator reads during an incident (about 10,800 lines a day).

Both processes apply this: the worker at startup, the API before it runs any
key inspector (PR 8a-3, follow-up S2).

WARNING rather than silence, deliberately: a request that FAILS still has to
say so, and that is the line nobody wants suppressed.
"""

import logging

_CLIENT_LOGGERS = ("httpx", "httpcore")


def silence_http_client_info_logs() -> None:
    """Sets ``httpx`` and ``httpcore`` to WARNING. Idempotent."""
    for name in _CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
