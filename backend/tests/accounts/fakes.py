"""Fakes shared by the ``SaveCredential`` tests and the store-script tests.

A recording inspector (so "no venue request was sent" is an assertion), a
recording writer and commit, and a ticking clock. All keys and secrets are FAKE:
no real credential anywhere (rule 1).
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.accounts.application.ports import CredentialWriterPort, KeyInspectorPort
from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
    KeyFacts,
)
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations, PermissionSnapshot
from strategy_manager.accounts.infrastructure.key_inspectors.registry import KeyInspectorRegistry

BYBIT_KEY = "BYBIT-FAKE-KEY-abcd"
BYBIT_SECRET = "BYBIT-FAKE-SECRET-wxyz"
BINANCE_KEY = "BINANCE-FAKE-KEY-efgh"
BINANCE_SECRET = "BINANCE-FAKE-SECRET-ijkl"

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)

BOTH = OwnerConfirmations(withdrawals_disabled=True, futures_enabled=True)
NEITHER = OwnerConfirmations()

TRADING_SNAPSHOT = PermissionSnapshot(wallet_permissions=frozenset(), read_only=False)
TRANSFER_SNAPSHOT = PermissionSnapshot(
    wallet_permissions=frozenset({"AccountTransfer"}), read_only=False
)
READ_ONLY_SNAPSHOT = PermissionSnapshot(
    wallet_permissions=frozenset({"AccountTransfer"}), read_only=True
)


def bybit_credential(api_key: str = BYBIT_KEY) -> ExchangeCredential:
    return ExchangeCredential(
        exchange="bybit", label="default", api_key=api_key, api_secret=BYBIT_SECRET
    )


def binance_credential(api_key: str = BINANCE_KEY) -> ExchangeCredential:
    return ExchangeCredential(
        exchange="binance", label="default", api_key=api_key, api_secret=BINANCE_SECRET
    )


class TickingClock:
    """A new instant on EVERY call, so a use case that asks twice stamps two
    different moments and a test comparing them notices."""

    def __init__(self, start: datetime = NOW) -> None:
        self._next = start

    def now(self) -> datetime:
        moment = self._next
        self._next = moment + timedelta(seconds=1)
        return moment


class RecordingInspector:
    """A fake venue that records every request it is asked to make."""

    def __init__(
        self, snapshot: PermissionSnapshot | None = None, error: Exception | None = None
    ) -> None:
        self._snapshot = snapshot if snapshot is not None else PermissionSnapshot()
        self._error = error
        self.calls: list[str] = []

    async def inspect(self, credential: ExchangeCredential) -> PermissionSnapshot:
        self.calls.append(credential.exchange)
        if self._error is not None:
            raise self._error
        return self._snapshot


class RecordingWriter:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.stored: list[tuple[ExchangeCredential, KeyFacts]] = []

    async def store(self, credential: ExchangeCredential, facts: KeyFacts) -> CredentialHint:
        if self._error is not None:
            raise self._error
        self.stored.append((credential, facts))
        return credential.hint(facts)


class RecordingCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def as_port(inspector: RecordingInspector) -> KeyInspectorPort:
    return inspector


def as_writer(writer: RecordingWriter) -> CredentialWriterPort:
    return writer


def registry_for(inspector: RecordingInspector) -> KeyInspectorRegistry:
    """One recording inspector standing behind both served exchanges."""
    return KeyInspectorRegistry({"bybit": as_port(inspector), "binance": as_port(inspector)})
