"""SQLAlchemy implementation of ``LedgerRepositoryPort`` against the
``ledger_entries`` table (migration ``0005``). Insert-only by contract; the
database enforces the same rule below the application layer with two
triggers (spec: trade-ledger § Append-Only Enforcement).
"""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.market_symbol import base_currency_of, market_spellings
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.reconciliation.domain.positions import LedgerPosition, OpenAllocation
from strategy_manager.signals.domain.holding import HeldAllocation


class SqlAlchemyLedgerRepository:
    """Implements ``LedgerRepositoryPort``, ``LedgerPositionReaderPort``,
    ``LedgerSymbolPositionReaderPort`` and ``LedgerSymbolHoldingsReaderPort``.
    No ``update``/``delete``/``mark`` method exists on this class — there is
    nothing here that could even attempt to mutate a written row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, entry: LedgerEntry) -> None:
        self._session.add(
            LedgerEntryRow(
                id=entry.id,
                strategy_id=entry.strategy_id,
                allocation_id=entry.allocation_id,
                execution_attempt_id=entry.execution_attempt_id,
                exchange=entry.exchange,
                venue=entry.venue,
                settlement_currency=entry.settlement_currency,
                symbol=entry.symbol,
                side=entry.side,
                quantity=entry.quantity,
                price=entry.price,
                fee=entry.fee,
                fee_currency=entry.fee_currency,
                notional=entry.notional,
                exchange_order_id=entry.exchange_order_id,
                exchange_fill_id=entry.exchange_fill_id,
                filled_at=entry.filled_at,
                usd_rate_at_fill=entry.usd_rate_at_fill,
            )
        )
        await self._session.flush()

    async def net_base_quantity(
        self, allocation_id: UUID, base_currency: str
    ) -> Decimal:
        """Implements ``LedgerPositionReaderPort``.

        One aggregate over one allocation's rows: buys add, sells subtract, and
        fees charged in the base currency subtract because that much of the
        purchase never arrived. The comparison is case-insensitive on both
        sides — the fee currency is whatever the exchange called it, and a
        mismatch of case would silently skip the subtraction and oversize every
        close.

        Backed by ``ix_ledger_allocation`` (migration ``0012``); without it
        this is a sequential scan of a table that only ever grows.
        """
        signed_quantity = case(
            (LedgerEntryRow.side == "BUY", LedgerEntryRow.quantity),
            else_=-LedgerEntryRow.quantity,
        )
        base_fee = case(
            (
                func.upper(LedgerEntryRow.fee_currency) == base_currency.upper(),
                LedgerEntryRow.fee,
            ),
            else_=0,
        )

        result = await self._session.execute(
            select(
                func.coalesce(func.sum(signed_quantity - base_fee), 0)
            ).where(LedgerEntryRow.allocation_id == allocation_id)
        )
        return Decimal(result.scalar_one())

    async def net_positions_by_symbol(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> list[LedgerPosition]:
        """Implements ``LedgerSymbolPositionReaderPort``.

        One aggregate over the WHOLE pool's rows, grouped by symbol and
        allocation — ``net_base_quantity``'s twin, generalised from one
        allocation to every allocation in the pool at once.

        Design decision 4's fee rule: the base-fee subtraction is keyed on
        ``fee_currency <> settlement_currency``, not on a ``base_currency``
        parameter this aggregate has no way to receive per symbol. Provably a
        no-op on USDⓈ-M, where every fee lands in the settlement currency
        (CLAUDE.md's verified Bybit round trip); load-bearing for a future
        spot/COIN-M pool where a fee IS paid in the base currency.

        ``HAVING`` drops any allocation whose net base sums to exactly zero —
        a fully closed allocation must vanish from the result as if it never
        existed, not survive as an ``OpenAllocation`` carrying nothing, so
        that ``classify()``'s rung 1 (``NO_MATCHING_ALLOCATION``, tested on
        an EMPTY tuple) still tells "never opened here" apart from "opened
        and closed cleanly".

        Backed by ``ix_ledger_pool_symbol`` (migration ``0020``); without it
        this is a sequential scan of a table that only ever grows.
        """
        signed_quantity = case(
            (LedgerEntryRow.side == "BUY", LedgerEntryRow.quantity),
            else_=-LedgerEntryRow.quantity,
        )
        settlement_fee = case(
            (
                func.upper(LedgerEntryRow.fee_currency) != settlement_currency.upper(),
                LedgerEntryRow.fee,
            ),
            else_=0,
        )
        net_base = func.sum(signed_quantity - settlement_fee)

        result = await self._session.execute(
            select(LedgerEntryRow.symbol, LedgerEntryRow.allocation_id, net_base)
            .where(
                LedgerEntryRow.exchange == exchange,
                LedgerEntryRow.venue == venue,
                LedgerEntryRow.settlement_currency == settlement_currency,
            )
            .group_by(LedgerEntryRow.symbol, LedgerEntryRow.allocation_id)
            .having(net_base != 0)
        )

        by_symbol: dict[str, list[OpenAllocation]] = defaultdict(list)
        for symbol, allocation_id, net in result.all():
            by_symbol[symbol].append(OpenAllocation(allocation_id, Decimal(net)))

        return [
            LedgerPosition(symbol, tuple(allocations))
            for symbol, allocations in by_symbol.items()
        ]

    async def symbol_holdings(
        self, exchange: str, venue: str, settlement_currency: str, symbol: str
    ) -> list[HeldAllocation]:
        """Implements ``LedgerSymbolHoldingsReaderPort``.

        One aggregate over one MARKET's rows -- merged across every spelling
        it wears (``market_spellings``) -- grouped by strategy AND
        allocation, across the WHOLE pool (every strategy that has ever
        touched this market, not just one). The caller reads out its own
        strategy's figure for the Existing-Position Guard (S2) and sums
        every row for the pool's net in orphan classification (S4); one
        query serves both (design.md § S2 "the query").

        The fee rule is ``base_currency_of``'s -- the same ``ReadHeldBase``
        and ``ClosePosition`` use (a fee charged IN THE BASE CURRENCY
        subtracts) -- deliberately NOT ``net_positions_by_symbol``'s
        settlement-currency rule, because this number must equal what a
        close of that specific allocation would size against, not a
        pool-wide aggregate with no single base currency of its own.

        ``HAVING`` drops any group whose net sums to exactly zero. Grouping
        by strategy and allocation only, never by the raw ``symbol`` column,
        is what makes this safe against the trap
        bug/reconciliation-symbol-spelling-mismatch fell into one layer up:
        an allocation opened as ``STXUSDT.P`` and closed as ``STXUSDT`` nets
        to zero here and vanishes, instead of surviving as two separate
        non-zero per-spelling groups.

        Backed by ``ix_ledger_pool_symbol`` (migration ``0020``), whose
        leading columns are ``(exchange, venue, settlement_currency)``; the
        ``symbol IN (...)`` filter narrows within that prefix.
        """
        base_currency = base_currency_of(symbol, settlement_currency)
        spellings = list(market_spellings(symbol))

        signed_quantity = case(
            (LedgerEntryRow.side == "BUY", LedgerEntryRow.quantity),
            else_=-LedgerEntryRow.quantity,
        )
        base_fee = case(
            (
                func.upper(LedgerEntryRow.fee_currency) == base_currency.upper(),
                LedgerEntryRow.fee,
            ),
            else_=0,
        )
        net_base = func.sum(signed_quantity - base_fee)

        result = await self._session.execute(
            select(LedgerEntryRow.strategy_id, LedgerEntryRow.allocation_id, net_base)
            .where(
                LedgerEntryRow.exchange == exchange,
                LedgerEntryRow.venue == venue,
                LedgerEntryRow.settlement_currency == settlement_currency,
                func.upper(LedgerEntryRow.symbol).in_(spellings),
            )
            .group_by(LedgerEntryRow.strategy_id, LedgerEntryRow.allocation_id)
            .having(net_base != 0)
        )

        return [
            HeldAllocation(
                strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal(net)
            )
            for strategy_id, allocation_id, net in result.all()
        ]

    async def recorded_fill_ids(
        self, exchange: str, venue: str, exchange_fill_ids: Sequence[str]
    ) -> frozenset[str]:
        """Implements ``RecordedFillIdsReaderPort``.

        Keyed on ``(exchange, venue, exchange_fill_id)`` --
        ``ux_ledger_exchange_fill`` (migration ``0019``) exactly, never
        symbol (design.md § 13's booking-domain testing rule: a booked close
        may legitimately carry a different spelling than the open it nets
        against, and keying this lookup on symbol would silently treat an
        already-recorded fill as unrecorded the moment a spelling differs).

        An empty ``exchange_fill_ids`` returns an empty set without a query
        -- ``IN ()`` is either a SQL error or an unconditional false
        depending on dialect/driver, and the caller (``match_fills``, via
        ``PrepareBooking``) never has a reason to ask this with nothing to
        check.
        """
        if not exchange_fill_ids:
            return frozenset()

        result = await self._session.execute(
            select(LedgerEntryRow.exchange_fill_id).where(
                LedgerEntryRow.exchange == exchange,
                LedgerEntryRow.venue == venue,
                LedgerEntryRow.exchange_fill_id.in_(exchange_fill_ids),
            )
        )
        return frozenset(row[0] for row in result.all())
