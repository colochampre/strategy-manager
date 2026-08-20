"""Ports (Protocols) owned by ``accounts``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
)

PoolKey = tuple[str, str]
"""A pool's identity: ``(venue, settlement_currency)``."""


class BalanceSourcePort(Protocol):
    """Reads a pool's raw balance from the exchange or a stand-in.
    Implementations MUST be local (DB or in-memory) — a synchronous remote
    call here would run inside the advisory lock once consumed by
    ``allocation.application.PoolBalancePort`` (design.md § Interfaces)."""

    async def read_balance(self, venue: str, settlement_currency: str) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class PoolBalanceReading:
    """One pool's balance as the exchange reported it.

    ``observed_at`` is the moment of the reading, not of the write. Freshness
    is judged against this field, so it must never be back-filled with a
    persistence timestamp.
    """

    venue: str
    settlement_currency: str
    available: Decimal
    observed_at: datetime


class ExchangeBalanceReaderPort(Protocol):
    """Reads live balances for the configured pools from the exchange.

    REMOTE by nature. This is the port ``BalanceSourcePort`` refuses to be:
    it must only ever be called from a background job, never from the
    allocation path, and never while a pool advisory lock is held.
    """

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]: ...


class BalanceSnapshotWriterPort(Protocol):
    """Persists readings so the allocation path can read them locally."""

    async def upsert(self, readings: Sequence[PoolBalanceReading]) -> None: ...


class CommitPort(Protocol):
    """The transaction boundary a use case closes when its work is done."""

    async def commit(self) -> None: ...


class CredentialVaultPort(Protocol):
    """Decrypts exchange API credentials at the moment of use.

    ``load`` returns a live secret and must only ever be called on the worker,
    immediately before signing (CLAUDE.md rule 8). Anything that merely needs
    to display or enumerate credentials calls ``hints`` instead.
    """

    async def load(self, exchange: str) -> ExchangeCredential: ...

    async def hints(self) -> list[CredentialHint]: ...
