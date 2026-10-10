"""Where the API process gives the root logger a level and a handler.

Placeholder committed with its tests (task alg.2, RED): the handler class is
final, the function does nothing yet.
"""

import logging
import sys


class ApiStreamHandler(logging.Handler):
    """The API's own handler on the root logger, writing to ``sys.stderr``."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stderr
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def configure_api_logging() -> None:
    """Does nothing yet."""
