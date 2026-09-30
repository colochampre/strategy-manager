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
    KeyFacts,
)
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot

PoolKey = tuple[str, str, str]
"""A pool's identity: ``(exchange, venue, settlement_currency)``."""


@dataclass(frozen=True, slots=True)
class PoolFunds:
    """The two figures a pool is judged by, in its settlement currency.

    ``total`` is what the pool holds, committed or not. It is the base a
    strategy's ``allocation_percent`` is applied to, so three strategies at
    30% each ask for the same amount whether or not the others already hold
    positions (owner decision 2026-09-15).

    ``available`` is what is still free to commit. It caps every grant.

    Two figures because they answer different questions. Sizing from
    ``available`` made the same configuration open different sizes depending
    on whether a balance sync happened to run between two signals.
    """

    total: Decimal
    available: Decimal


class BalanceSourcePort(Protocol):
    """Reads a pool's funds from the exchange or a stand-in.
    Implementations MUST be local (DB or in-memory) — a synchronous remote
    call here would run inside the advisory lock once consumed by
    ``allocation.application.PoolBalancePort`` (design.md § Interfaces)."""

    async def read_balance(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolFunds: ...


@dataclass(frozen=True, slots=True)
class PoolBalanceReading:
    """One pool's balance as the exchange reported it.

    ``total`` excludes unrealized PnL: sizing on paper gains would grow the
    next position out of money that has not been realized.

    ``observed_at`` is the moment of the reading, not of the write. Freshness
    is judged against this field, so it must never be back-filled with a
    persistence timestamp.
    """

    exchange: str
    venue: str
    settlement_currency: str
    total: Decimal
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


class BalanceSnapshotAgePort(Protocol):
    """Reads how old a pool's last stored snapshot is, WITHOUT the freshness
    refusal ``BalanceSourcePort.read_balance`` applies -- used by
    ``RefreshPoolBalance`` (application/accounts) to decide FALLBACK vs
    UNAVAILABLE after an on-demand refresh fails (design.md § S3).

    ``None`` means no snapshot has ever been synced for the pool -- there is
    nothing to fall back to, so this always resolves to UNAVAILABLE regardless
    of the fallback bound.
    """

    async def age_seconds(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> float | None: ...


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


class CredentialWriterPort(Protocol):
    """Stores a credential and makes it the active one for its exchange.

    Deliberately has NO ``load``: the save path seals and never opens. Only the
    worker decrypts, at signing time (CLAUDE.md rule 8, decision 5). Raises
    ``ConcurrentCredentialSave`` when another save for the same exchange won the
    race.
    """

    async def store(self, credential: ExchangeCredential, facts: KeyFacts) -> CredentialHint: ...


class CapitalPoolWriterPort(Protocol):
    """Switches a pool on or off. It is NOT a management surface: nothing on the
    API calls it directly, and neither method takes a pool identity.

    The exchange is the only input. Which pool that means, and the
    ``min_order_size`` a row created from scratch starts with, come from
    ``KNOWN_FUTURES_POOLS`` (owner decision 21), never from a request body. An
    exchange that constant does not name raises; there is no fallback pool.

    Both write through the caller's session, so they commit with the caller's
    transaction and roll back with it.
    """

    async def enable(self, exchange: str) -> bool:
        """Makes the exchange's pool enabled, creating the row when it does not
        exist. An existing row's ``min_order_size`` is never touched. Returns
        ``True`` when this call changed something (row inserted, or flipped from
        disabled) and ``False`` when the pool was already enabled."""
        ...

    async def disable(self, exchange: str) -> bool:
        """Flips only an existing row to disabled; a missing row is not created.
        Returns ``True`` when an enabled row was flipped."""
        ...


class KeyInspectorPort(Protocol):
    """Asks a venue what a candidate key is allowed to do, before it is stored.

    GET-only by contract: an inspector never places an order and never changes
    a setting. It runs the live read (rule 8a) and returns only the derived
    ``PermissionSnapshot``, never the venue's payload.

    Raises ``KeyRejected`` when the venue refuses the key and
    ``VenueUnreachable`` when it could not be asked. The candidate credential
    is passed in because it is not stored yet; nothing here decrypts a vault
    row.
    """

    async def inspect(self, credential: ExchangeCredential) -> PermissionSnapshot: ...


class KeyInspectorRegistryPort(Protocol):
    """Selects the inspector for an exchange. An unserved exchange raises; there
    is no fallback."""

    def for_exchange(self, exchange: str) -> KeyInspectorPort: ...
