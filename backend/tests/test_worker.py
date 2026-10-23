"""The worker's startup vault self-test.

A master key that is well-formed but WRONG builds a cipher without complaint
and only fails when a credential is opened — per job, five retries deep, inside
a handler. For ``balance.sync`` that kills the recurring chain with nothing
scheduled to revive it, so the deployment stops learning its own capital while
looking alive. This check moves that failure to startup.
"""

import logging
from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
    KeyFacts,
)
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.crypto import DecryptionFailed
from strategy_manager.worker import (
    _assert_keys_present,
    _assert_sealed_credentials_open,
    _configure_logging,
    _log_vault_self_test,
)
from tests.owner import OWNER_ID

_BYBIT_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=OWNER_ID,
    min_order_size=Decimal("10"),
)
_BINANCE_POOL = PoolConfig(
    exchange=Exchange.BINANCE,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=OWNER_ID,
    min_order_size=Decimal("10"),
)


OTHER_ID = UUID("5ec0d0b2-0000-4000-8000-0000000000b2")


class FakeVault:
    """A vault holding whichever credentials open and whichever do not, per
    user: ``opens`` and ``fails`` are the owner's, ``others`` another user's
    keys that open and ``other_fails`` another user's that do not."""

    def __init__(
        self,
        *,
        opens: tuple[str, ...] = (),
        fails: tuple[str, ...] = (),
        others: tuple[str, ...] = (),
        other_fails: tuple[str, ...] = (),
    ) -> None:
        self._keys = {OWNER_ID: (*opens, *fails), OTHER_ID: (*others, *other_fails)}
        self._fails = {(OWNER_ID, e) for e in fails} | {(OTHER_ID, e) for e in other_fails}
        self.loaded: list[tuple[UUID, str]] = []

    async def hints(self, user_id: UUID) -> list[CredentialHint]:
        return [
            CredentialHint(
                exchange=exchange,
                label="default",
                api_key_last4="wxyz",
                facts=KeyFacts.unrecorded(trade_capable=True),
            )
            for exchange in self._keys.get(user_id, ())
        ]

    async def load(self, user_id: UUID, exchange: str) -> ExchangeCredential:
        self.loaded.append((user_id, exchange))
        if (user_id, exchange) in self._fails:
            raise DecryptionFailed(
                f"could not unwrap the data key for '{exchange}'"
            )
        return ExchangeCredential(
            exchange=exchange, label="default", api_key="KEY-wxyz", api_secret="SECRET"
        )


async def test_every_sealed_credential_is_opened_at_startup() -> None:
    vault = FakeVault(opens=("bybit", "binance"))

    opened = await _assert_sealed_credentials_open(vault, [OWNER_ID])

    assert opened == [(OWNER_ID, "bybit"), (OWNER_ID, "binance")]
    assert vault.loaded == [(OWNER_ID, "bybit"), (OWNER_ID, "binance")]


async def test_every_users_sealed_keys_are_opened_each_as_that_user() -> None:
    """Multi-user design AD9: keys are opened per ``(user, exchange)``, so a
    second user's Bybit key is opened as theirs, beside the owner's."""
    vault = FakeVault(opens=("bybit",), others=("bybit", "binance"))

    opened = await _assert_sealed_credentials_open(vault, [OWNER_ID, OTHER_ID])

    assert opened == [(OWNER_ID, "bybit"), (OTHER_ID, "bybit"), (OTHER_ID, "binance")]
    assert vault.loaded == opened


async def test_a_credential_that_will_not_decrypt_refuses_startup() -> None:
    with pytest.raises(InvariantViolation, match="cannot be decrypted"):
        await _assert_sealed_credentials_open(FakeVault(fails=("binance",)), [OWNER_ID])


async def test_the_failure_names_the_exchange_and_the_key_hint() -> None:
    """An operator reading this in a crash log has to know WHICH stored key
    the running master key cannot open. The last four is the most that may
    ever be rendered (CLAUDE.md rule 8)."""
    with pytest.raises(InvariantViolation, match=r"'binance' \(key \*\*\*wxyz\)"):
        await _assert_sealed_credentials_open(FakeVault(fails=("binance",)), [OWNER_ID])


async def test_the_failure_names_the_users_id_prefix_never_an_email() -> None:
    """The refusal reaches Telegram, so the user is named by the first 8 hex of
    their id (AD9), which is all this check knows of them."""
    with pytest.raises(InvariantViolation, match="user 5ec0d0b2") as refused:
        await _assert_sealed_credentials_open(
            FakeVault(opens=("bybit",), other_fails=("bybit",)), [OWNER_ID, OTHER_ID]
        )

    assert "@" not in str(refused.value)


async def test_the_failure_names_the_master_key_as_the_cause() -> None:
    """Not "the exchange is unavailable". A key that cannot open these rows is
    the wrong key or the rows were altered, and both mean stop."""
    with pytest.raises(InvariantViolation, match="MASTER_ENCRYPTION_KEY"):
        await _assert_sealed_credentials_open(FakeVault(fails=("bybit",)), [OWNER_ID])


async def test_one_unreadable_credential_stops_the_worker_for_all_of_them() -> None:
    """Deliberately NOT the per-exchange degradation ``_vault_credential``
    applies to a MISSING credential. A missing key means nobody sealed one; an
    unreadable one means the key in this process does not match the vault, and
    that is true of every row in it -- every user's too (tasks.md B.7: the
    startup refusal is unchanged)."""
    with pytest.raises(InvariantViolation):
        await _assert_sealed_credentials_open(
            FakeVault(opens=("bybit",), fails=("binance",)), [OWNER_ID]
        )
    with pytest.raises(InvariantViolation):
        await _assert_sealed_credentials_open(
            FakeVault(opens=("bybit",), other_fails=("binance",)), [OWNER_ID, OTHER_ID]
        )


def test_the_http_client_does_not_log_every_signed_request() -> None:
    """httpx logs one INFO per request, and this process makes one balance
    read per exchange every 60s -- about 10,800 lines a day, drowning the log
    an operator reads during an incident. Those lines also carry the signed
    venue URL, `timestamp` and `signature` included.

    WARNING, not silence: a failing request must still say so.
    """
    _configure_logging()

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING
    # Only those two are pinned. This system's own loggers are left at NOTSET
    # so they keep inheriting whatever the root is configured to -- asserting
    # an effective level here would only measure the root handler pytest
    # installed, not anything this function did.
    assert logging.getLogger("strategy_manager.worker").level == logging.NOTSET


def test_an_opened_vault_is_reported_at_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="strategy_manager.worker"):
        _log_vault_self_test([(OWNER_ID, "bybit"), (OTHER_ID, "binance")], dry_run=False)

    record = caplog.records[-1]
    assert record.levelno == logging.INFO
    assert "bybit" in record.getMessage() and "binance" in record.getMessage()
    assert str(OTHER_ID)[:8] in record.getMessage()


def test_an_empty_vault_warns_rather_than_refusing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="strategy_manager.worker"):
        _log_vault_self_test([], dry_run=False)

    assert caplog.records[-1].levelno == logging.WARNING


def test_an_empty_vault_under_dry_run_names_balance_sync(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The self-test now runs under DRY_RUN too, because balance.sync opens
    the stored credential there as well — only ORDERS are faked. An operator
    rehearsing with an empty vault must be told which job will fail, not that
    the vault goes unread."""
    with caplog.at_level(logging.INFO, logger="strategy_manager.worker"):
        _log_vault_self_test([], dry_run=True)

    message = caplog.records[-1].getMessage()
    assert caplog.records[-1].levelno == logging.WARNING
    assert "balance.sync" in message


async def test_an_empty_vault_is_not_a_failure() -> None:
    """A fresh deployment has sealed nothing yet, and the sealing scripts need
    this database and this configuration to run at all. Refusing here would
    make the first boot — the one that has to happen first — impossible."""
    assert await _assert_sealed_credentials_open(FakeVault(), []) == []


# --- 1b.3/1b.4: _assert_keys_present (decision 20, startup DEGRADED set) ----


def test_missing_key_for_enabled_pool_logs_one_error_and_still_starts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Binance has an enabled pool but no active vault credential at all
    (never sealed, as opposed to sealed-but-undecryptable). Unlike
    ``_assert_sealed_credentials_open``, this must NEVER raise: the worker
    still starts and keeps trading every other exchange (decision 20)."""
    active = frozenset({(OWNER_ID, "bybit")})

    with caplog.at_level(logging.ERROR, logger="strategy_manager.worker"):
        degraded = _assert_keys_present(active, [_BYBIT_POOL, _BINANCE_POOL])

    assert degraded == frozenset({(OWNER_ID, "binance")})
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "binance" in message
    assert "store_binance_credentials.py" in message
    assert str(OWNER_ID)[:8] in message


def test_degraded_exchange_does_not_affect_any_other_exchange(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Binance DEGRADED, Bybit healthy: the function must name ONLY the
    exchange that is actually missing a key, never the one that has one --
    the same per-exchange isolation ``_vault_credential`` already applies to
    orders, applied here to the startup report."""
    active = frozenset({(OWNER_ID, "bybit")})

    with caplog.at_level(logging.ERROR, logger="strategy_manager.worker"):
        degraded = _assert_keys_present(active, [_BYBIT_POOL, _BINANCE_POOL])

    assert (OWNER_ID, "binance") in degraded
    assert (OWNER_ID, "bybit") not in degraded
    assert any("binance" in r.getMessage() for r in caplog.records)
    assert not any("bybit" in r.getMessage() for r in caplog.records)


def test_one_users_missing_key_degrades_only_that_users_pair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AD9: the owner holds a Bybit key, another user holds a Bybit pool and no
    key. Only the other user's pair is DEGRADED; the owner's key does not cover
    it, and the ERROR names the other user's id prefix, never an e-mail."""
    others_pool = PoolConfig(
        exchange=Exchange.BYBIT,
        venue=Venue.USDT_M,
        settlement_currency=Currency.USDT,
        user_id=OTHER_ID,
        min_order_size=Decimal("10"),
    )

    with caplog.at_level(logging.ERROR, logger="strategy_manager.worker"):
        degraded = _assert_keys_present(
            frozenset({(OWNER_ID, "bybit")}), [_BYBIT_POOL, others_pool]
        )

    assert degraded == frozenset({(OTHER_ID, "bybit")})
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert str(OTHER_ID)[:8] in errors[0]
    assert str(OWNER_ID)[:8] not in errors[0]
    assert "@" not in errors[0]


def test_every_configured_exchange_holding_a_key_logs_nothing_and_degrades_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Triangulation: a fully healthy vault must not be reported as
    DEGRADED, and must not log a single ERROR -- proves the function is not
    unconditionally returning an empty/non-empty set regardless of input."""
    active = frozenset({(OWNER_ID, "bybit"), (OWNER_ID, "binance")})

    with caplog.at_level(logging.ERROR, logger="strategy_manager.worker"):
        degraded = _assert_keys_present(active, [_BYBIT_POOL, _BINANCE_POOL])

    assert degraded == frozenset()
    assert not any(r.levelno == logging.ERROR for r in caplog.records)
