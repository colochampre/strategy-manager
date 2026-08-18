"""Ports (Protocols) owned by ``accounts``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from decimal import Decimal
from typing import Protocol


class BalanceSourcePort(Protocol):
    """Reads a pool's raw balance from the exchange or a stand-in.
    Implementations MUST be local (DB or in-memory) — a synchronous remote
    call here would run inside the advisory lock once consumed by
    ``allocation.application.PoolBalancePort`` (design.md § Interfaces)."""

    async def read_balance(self, venue: str, settlement_currency: str) -> Decimal: ...
