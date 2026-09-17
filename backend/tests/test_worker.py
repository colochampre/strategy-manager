"""The worker's startup vault self-test.

A master key that is well-formed but WRONG builds a cipher without complaint
and only fails when a credential is opened — per job, five retries deep, inside
a handler. For ``balance.sync`` that kills the recurring chain with nothing
scheduled to revive it, so the deployment stops learning its own capital while
looking alive. This check moves that failure to startup.
"""

import pytest

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.crypto import DecryptionFailed
from strategy_manager.worker import _assert_sealed_credentials_open


class FakeVault:
    """A vault holding whichever credentials open and whichever do not."""

    def __init__(
        self, *, opens: tuple[str, ...] = (), fails: tuple[str, ...] = ()
    ) -> None:
        self._opens = opens
        self._fails = fails
        self.loaded: list[str] = []

    async def hints(self) -> list[CredentialHint]:
        return [
            CredentialHint(exchange=exchange, label="default", api_key_last4="wxyz")
            for exchange in (*self._opens, *self._fails)
        ]

    async def load(self, exchange: str) -> ExchangeCredential:
        self.loaded.append(exchange)
        if exchange in self._fails:
            raise DecryptionFailed(
                f"could not unwrap the data key for '{exchange}'"
            )
        return ExchangeCredential(
            exchange=exchange, label="default", api_key="KEY-wxyz", api_secret="SECRET"
        )


async def test_every_sealed_credential_is_opened_at_startup() -> None:
    vault = FakeVault(opens=("bybit", "binance"))

    opened = await _assert_sealed_credentials_open(vault)

    assert opened == ["bybit", "binance"]
    assert vault.loaded == ["bybit", "binance"]


async def test_a_credential_that_will_not_decrypt_refuses_startup() -> None:
    with pytest.raises(InvariantViolation, match="cannot be decrypted"):
        await _assert_sealed_credentials_open(FakeVault(fails=("binance",)))


async def test_the_failure_names_the_exchange_and_the_key_hint() -> None:
    """An operator reading this in a crash log has to know WHICH stored key
    the running master key cannot open. The last four is the most that may
    ever be rendered (CLAUDE.md rule 8)."""
    with pytest.raises(InvariantViolation, match=r"'binance' \(key \*\*\*wxyz\)"):
        await _assert_sealed_credentials_open(FakeVault(fails=("binance",)))


async def test_the_failure_names_the_master_key_as_the_cause() -> None:
    """Not "the exchange is unavailable". A key that cannot open these rows is
    the wrong key or the rows were altered, and both mean stop."""
    with pytest.raises(InvariantViolation, match="MASTER_ENCRYPTION_KEY"):
        await _assert_sealed_credentials_open(FakeVault(fails=("bybit",)))


async def test_one_unreadable_credential_stops_the_worker_for_all_of_them() -> None:
    """Deliberately NOT the per-exchange degradation ``_vault_credential``
    applies to a MISSING credential. A missing key means nobody sealed one; an
    unreadable one means the key in this process does not match the vault, and
    that is true of every row in it."""
    with pytest.raises(InvariantViolation):
        await _assert_sealed_credentials_open(
            FakeVault(opens=("bybit",), fails=("binance",))
        )


async def test_an_empty_vault_is_not_a_failure() -> None:
    """A fresh deployment has sealed nothing yet, and the sealing scripts need
    this database and this configuration to run at all. Refusing here would
    make the first boot — the one that has to happen first — impossible."""
    assert await _assert_sealed_credentials_open(FakeVault()) == []
