"""What must never leave this process inside an alert.

An alert body is assembled from log records, and the log is not a curated
surface: httpx logs the signed venue URL at INFO, and a traceback has already
printed a database DSN once. Telegram is a third party and a phone is not a
secure store, so the body is scrubbed on the way out rather than at every site
that could ever log something.

Each rule below exists because the thing it removes has actually been observed
in this system's own log.
"""

from strategy_manager.shared.infrastructure.alert_redaction import redact


def test_a_signed_venue_url_loses_its_query_string() -> None:
    """The signature, the api_key and the timestamp all ride in the query. The
    path is kept: which endpoint failed is the whole diagnostic value."""

    scrubbed = redact(
        "GET https://api.bybit.com/v5/account/wallet-balance"
        "?accountType=UNIFIED&api_key=AAAABBBBCCCC&sign=deadbeefcafe failed"
    )

    assert "AAAABBBBCCCC" not in scrubbed
    assert "deadbeefcafe" not in scrubbed
    assert "https://api.bybit.com/v5/account/wallet-balance" in scrubbed


def test_the_query_string_is_marked_rather_than_erased() -> None:
    """A redacted URL still has to show that a query was present, or a call
    carrying credentials looks identical to one that carried none."""

    assert redact("https://api.bybit.com/v5/x?sign=abc") == (
        "https://api.bybit.com/v5/x?REDACTED"
    )


def test_a_database_dsn_loses_its_password() -> None:
    """The exact shape a SQLAlchemy traceback printed: scheme://user:pass@host."""

    scrubbed = redact(
        "could not connect to "
        "postgresql+asyncpg://postgres:hunter2@localhost:5432/strategy_manager"
    )

    assert "hunter2" not in scrubbed
    assert "postgres:" not in scrubbed
    assert "@localhost:5432/strategy_manager" in scrubbed


def test_a_telegram_bot_token_is_removed_from_a_url_path() -> None:
    """The alerter's own token lives in the PATH, not the query, so stripping
    the query does not reach it. An httpx error naming the request URL would
    otherwise carry the token into the very channel it authenticates."""

    scrubbed = redact(
        "POST https://api.telegram.org/bot8123456789:AAH1z_kQm0pQrStUvWxYz012345678ab"
        "/sendMessage timed out"
    )

    assert "AAH1z_kQm0pQrStUvWxYz012345678ab" not in scrubbed
    assert "8123456789" not in scrubbed
    assert "sendMessage" in scrubbed


def test_an_api_secret_in_a_key_value_pair_is_removed() -> None:
    """A repr of a credential object, a JSON body, a kwargs dump — the value is
    removed and the NAME is kept, exactly as the access log does it, so the
    reader still learns that a secret was in play."""

    scrubbed = redact(
        "BybitCredentials(api_key='KEY-wxyz', api_secret='s3cr3t-value-here')"
    )

    assert "s3cr3t-value-here" not in scrubbed
    assert "KEY-wxyz" not in scrubbed
    assert "api_secret" in scrubbed


def test_a_json_secret_field_is_removed() -> None:
    scrubbed = redact('{"token": "abc123def456", "retCode": 0}')

    assert "abc123def456" not in scrubbed
    assert "retCode" in scrubbed


def test_ordinary_text_is_left_exactly_as_it_was() -> None:
    """Redaction that mangles a normal message costs the alert its meaning."""

    message = "balance.sync failed after 5 attempts: pool bybit/usdt-m/USDT is stale"

    assert redact(message) == message
