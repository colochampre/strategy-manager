"""Ports internal to ``ledger``. ``execution`` never sees these — it knows
only ``execution.application.ports.FillRecorderPort`` and
``HeldPositionPort``, which ``RecordFill`` and ``ReadHeldBase`` implement
(design.md's component inventory § ledger/application/ports.py).

``LedgerSymbolPositionReaderPort`` is the same shape of split, one level up,
for ``reconciliation``: the consumer (``reconciliation.application.ports``)
declares ``LedgerSymbolPositionPort`` and owns ``LedgerPosition``/
``OpenAllocation``; this internal port is what ``ReadSymbolPositions`` (the
adapter implementing that consumer port) asks the repository for, exactly the
way ``ReadHeldBase`` asks ``LedgerPositionReaderPort`` for a single
allocation's number.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.reconciliation.domain.positions import LedgerPosition
from strategy_manager.signals.domain.holding import HeldAllocation


class LedgerRepositoryPort(Protocol):
    """Insert-only by contract; the database enforces it below the
    application layer too (spec: trade-ledger § Append-Only Enforcement)."""

    async def insert(self, entry: LedgerEntry) -> None: ...


class LedgerPositionReaderPort(Protocol):
    """Reading the ledger is not in tension with its append-only rule — that
    rule governs writes, and rule 6 says positions are a projection *over*
    these rows. This port is deliberately separate from the write port so the
    insert-only guarantee stays visible in ``LedgerRepositoryPort``: no adapter
    gains a mutating method by acquiring a read.
    """

    async def net_base_quantity(
        self, allocation_id: UUID, base_currency: str
    ) -> Decimal: ...


class LedgerSymbolPositionReaderPort(Protocol):
    """One query per WHOLE POOL, grouped by symbol — unlike
    ``net_base_quantity``, which is one query per allocation.

    Implementations own design decision 4's fee rule: a fill's quantity is
    subtracted from its allocation's running net base only when that fill's
    ``fee_currency`` differs from ``settlement_currency`` — keyed on the
    fee's own currency, never on parsing a base currency out of the symbol,
    because this aggregate spans every symbol in the pool at once and never
    receives one ``base_currency`` the way ``net_base_quantity`` does.

    An allocation only appears in the returned ``LedgerPosition.open_allocations``
    when its own net base is non-zero — a fully closed allocation nets to
    zero and must vanish from the result exactly like it never existed,
    which is what lets ``classify()``'s rung 1 (``NO_MATCHING_ALLOCATION``)
    tell "no allocation was ever open here" apart from "one was open and
    closed cleanly".
    """

    async def net_positions_by_symbol(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> list[LedgerPosition]: ...


class LedgerSymbolHoldingsReaderPort(Protocol):
    """One query per MARKET -- merged across every spelling it wears
    (``market_spellings``) -- grouped by strategy AND allocation, unlike
    ``net_positions_by_symbol`` which groups by raw symbol AND allocation
    across the WHOLE pool.

    Implementations own design decision 4's fee rule the same way
    ``net_base_quantity`` does: a fill's quantity is subtracted from its
    allocation's running net base only when its ``fee_currency`` matches the
    market's own base currency (``base_currency_of``) -- not
    ``net_positions_by_symbol``'s settlement-currency rule, because this
    number must equal what a close of that specific allocation would size
    against.

    Grouping by strategy and allocation only (never by the raw symbol
    column) is what lets an allocation opened under one spelling and closed
    under another still net to exactly zero and vanish under ``HAVING`` --
    grouping by spelling first, as ``net_positions_by_symbol`` does, would
    see two separate non-zero halves and never net them out (the trap
    bug/reconciliation-symbol-spelling-mismatch fell into one layer up).
    """

    async def symbol_holdings(
        self, exchange: str, venue: str, settlement_currency: str, symbol: str
    ) -> list[HeldAllocation]: ...


class RecordedFillIdsReaderPort(Protocol):
    """Which of a candidate set of fill ids ``ledger_entries`` already
    holds, keyed on ``(exchange, venue, exchange_fill_id)`` --
    ``ux_ledger_exchange_fill`` (migration ``0019``) exactly, never symbol.

    The same split every other port in this file already draws between the
    consumer-declared protocol (``reconciliation.application.ports
    .RecordedFillIdsPort``) and this internal one: what ``ReadRecordedFillIds``
    asks the repository for, one level down from what
    ``reconciliation`` asks ``ReadRecordedFillIds`` for.
    """

    async def recorded_fill_ids(
        self, exchange: str, venue: str, exchange_fill_ids: Sequence[str]
    ) -> frozenset[str]: ...
