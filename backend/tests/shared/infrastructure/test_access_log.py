"""Unit tests for access-log redaction.

The webhook secret rides in the query string, so uvicorn's access logger would
otherwise write it to disk on every alert.
"""

import logging

from strategy_manager.shared.infrastructure.access_log import (
    RedactQuerySecretsFilter,
    install_access_log_redaction,
    redact_query_secrets,
)

REQUEST_LINE = "POST /webhook/tradingview?secret=s3cr3t HTTP/1.1"


def _record(msg: str, args: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,  # type: ignore[arg-type]
        exc_info=None,
    )


def test_the_secret_value_is_replaced() -> None:
    assert "s3cr3t" not in redact_query_secrets(REQUEST_LINE)


def test_the_parameter_name_survives_redaction() -> None:
    """A redacted line still has to show a secret was present, or a request
    carrying one looks identical to a request missing one."""
    assert "secret=REDACTED" in redact_query_secrets(REQUEST_LINE)


def test_the_path_and_method_are_untouched() -> None:
    redacted = redact_query_secrets(REQUEST_LINE)

    assert redacted.startswith("POST /webhook/tradingview?secret=")
    assert redacted.endswith("HTTP/1.1")


def test_other_query_parameters_are_left_readable() -> None:
    redacted = redact_query_secrets("/webhook/tradingview?symbol=BTCUSDT&secret=s3cr3t")

    assert "symbol=BTCUSDT" in redacted
    assert "s3cr3t" not in redacted


def test_an_empty_secret_value_is_still_redacted() -> None:
    assert redact_query_secrets("/hook?secret=") == "/hook?secret=REDACTED"


def test_neighbouring_credential_names_are_covered() -> None:
    for name in ("token", "api_key", "api-key", "apikey", "password"):
        assert "s3cr3t" not in redact_query_secrets(f"/hook?{name}=s3cr3t")


def test_a_line_with_no_secret_is_unchanged() -> None:
    line = "GET /health HTTP/1.1"

    assert redact_query_secrets(line) == line


def test_the_filter_rewrites_uvicorn_style_args() -> None:
    """Uvicorn passes the request line through ``record.args``, not ``msg``."""
    record = _record('%s - "%s" %d', ("127.0.0.1:1234", REQUEST_LINE, 200))

    assert RedactQuerySecretsFilter().filter(record) is True
    assert "s3cr3t" not in record.getMessage()
    assert "secret=REDACTED" in record.getMessage()


def test_the_filter_rewrites_dict_args() -> None:
    """``logger.info("%(line)s", {...})`` reaches ``LogRecord`` as a 1-tuple
    holding the mapping, which ``LogRecord`` then unwraps."""
    record = _record("%(line)s", ({"line": REQUEST_LINE},))

    RedactQuerySecretsFilter().filter(record)

    assert "s3cr3t" not in record.getMessage()


def test_the_filter_rewrites_a_bare_message() -> None:
    record = _record(REQUEST_LINE)

    RedactQuerySecretsFilter().filter(record)

    assert "s3cr3t" not in record.getMessage()


def test_the_filter_never_drops_a_record() -> None:
    """It redacts; it is not a log level. A dropped access line is a lost
    audit trail."""
    record = _record("GET /health HTTP/1.1")

    assert RedactQuerySecretsFilter().filter(record) is True


def test_installation_is_idempotent() -> None:
    """The composition root may run more than once in a test session, and a
    stack of identical filters would be noise."""
    logger = logging.getLogger("test.access.idempotent")
    logger.filters.clear()

    install_access_log_redaction(("test.access.idempotent",))
    install_access_log_redaction(("test.access.idempotent",))

    assert sum(isinstance(f, RedactQuerySecretsFilter) for f in logger.filters) == 1


def test_an_installed_filter_redacts_records_logged_through_that_logger() -> None:
    logger = logging.getLogger("test.access.effective")
    logger.filters.clear()
    install_access_log_redaction(("test.access.effective",))
    seen: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger.addHandler(_Capture())
    logger.setLevel(logging.INFO)
    try:
        logger.info('%s - "%s" %d', "127.0.0.1:1234", REQUEST_LINE, 200)
    finally:
        logger.handlers.clear()
        logger.filters.clear()

    assert seen and "s3cr3t" not in seen[0]
