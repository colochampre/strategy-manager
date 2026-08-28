"""Keeps the webhook's shared secret out of the access log.

TradingView controls only the URL and the alert body, so the secret has to
travel in one of the two. It travels in the URL because the body is persisted
verbatim into ``signals.raw_payload`` (a ``JSONB`` column, ``nullable=False``):
a secret placed there would be stored in plaintext, in every signal row, and in
every backup, forever — and stripping it before persistence is a defence whose
failure is silent.

The URL is the lesser exposure, not a free one. Uvicorn's access logger writes
the full request line, query string included, so without this filter the secret
lands in a log file on every single alert.
"""

import logging
import re

# Redacts the webhook secret and the obvious neighbours a future endpoint might
# reach for, so this does not have to be revisited to stay correct.
_SECRET_QUERY_PARAM = re.compile(r"(?i)([?&](?:secret|token|api[-_]?key|password)=)[^&\s]*")

_DEFAULT_LOGGERS = ("uvicorn.access",)


def redact_query_secrets(text: str) -> str:
    """Replaces the VALUE of a secret-bearing query parameter, keeping its name.

    The name is left visible on purpose: a redacted line still has to show that
    a secret was present, or a request missing one looks identical to a request
    carrying one.
    """

    return _SECRET_QUERY_PARAM.sub(r"\1REDACTED", text)


class RedactQuerySecretsFilter(logging.Filter):
    """Rewrites secret query parameters out of a record before it is emitted.

    A filter rather than a formatter, because a formatter is per-handler and
    this has to hold for whatever handlers uvicorn or the deployment attach.
    Uvicorn passes the request line through ``record.args``, so both the args
    and the message template are rewritten.

    Always returns ``True``: this redacts records, it never drops them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_query_secrets(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_query_secrets(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        if isinstance(record.msg, str):
            record.msg = redact_query_secrets(record.msg)
        return True


def install_access_log_redaction(logger_names: tuple[str, ...] = _DEFAULT_LOGGERS) -> None:
    """Attaches the filter to the loggers that write request lines.

    Idempotent, because the composition root may be invoked more than once in
    a test session and a stack of identical filters would be noise.
    """

    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactQuerySecretsFilter) for f in logger.filters):
            logger.addFilter(RedactQuerySecretsFilter())
