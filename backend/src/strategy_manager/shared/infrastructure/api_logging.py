"""Where the API process gives the root logger a level and a handler.

The worker calls ``logging.basicConfig`` at startup. The API never did, and
uvicorn's own logging configuration touches only the ``uvicorn``,
``uvicorn.error`` and ``uvicorn.access`` loggers. So in the API the root logger
sat at WARNING with no handler: every INFO line of the system was dropped
(the origin's startup line, a changed share, a deleted strategy, "operator
alerts are on"), and once ``operator_alerts`` put a handler on the root logger
a WARNING or an ERROR was written nowhere either, because ``logging.lastResort``
is used only when NO handler is found. The tests did not see it: ``caplog``
installs its own root handler and level.

**Not ``logging.basicConfig``.** It does nothing when the root logger already
has a handler, and pytest's capture and the alert bridge are both such
handlers. This function recognises its OWN handler by type, so it neither
depends on what else is installed nor installs a second copy of itself.

**Uvicorn's lines are not doubled.** ``uvicorn`` and ``uvicorn.access`` have
``propagate: False`` in uvicorn's configuration, so a root handler does not
repeat them.

The HTTP client's INFO lines stay out: ``silence_http_client_info_logs`` sets
``httpx`` and ``httpcore`` to WARNING on their own loggers, which a level on
the root logger does not override.
"""

import logging
import sys

# The worker's format, so one journal reads the same from both processes.
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class ApiStreamHandler(logging.Handler):
    """The API's own handler on the root logger, writing to ``sys.stderr``.

    ``sys.stderr`` is looked up on every record rather than held from the
    moment of installation, so a stream that was replaced afterwards (a test
    runner's capture, a redirect) is never written to after it was closed.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stderr
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def configure_api_logging() -> None:
    """INFO for the whole process, written to stderr. Idempotent."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(handler, ApiStreamHandler) for handler in root.handlers):
        return
    handler = ApiStreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
