"""``FakeVenueBook``: DRY_RUN's in-memory stand-in for a venue's own reported
net position (design.md § S4, DRY_RUN paragraph).

Keyed by ``(exchange, market)`` rather than the full pool tuple: within one
exchange, every configured pool trades a disjoint set of symbols in this
system (a USDⓈ-M pool never shares a symbol with a COIN-M pool on the same
exchange), so the coarser key is exact for every configuration this app
supports -- and it is what ``FakeExchangeAdapter``, which knows its own
exchange and an order's symbol but never the pool a signal was sized
against, can supply without threading a settlement currency through the
whole placing path.

Seeded LAZILY, one pool at a time, the first time that exact pool is asked
about: a worker restart must not turn an already-open DRY_RUN position into
a ghost, so the book's first answer for a never-before-seen market is
whatever the ledger already says is open on it, not zero.
"""

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal

from strategy_manager.execution.domain.market_symbol import strip_contract_marker

_PoolKey = tuple[str, str, str]

PoolLedgerReader = Callable[[_PoolKey], Awaitable[Sequence[tuple[str, Decimal]]]]
"""Reads every symbol this pool's ledger currently holds a non-zero net on,
as ``(symbol, net_base)`` pairs -- exactly what
``reconciliation.application.ports.LedgerSymbolPositionPort.net_positions_by_symbol``
already answers. Bound by the composition root (main.py), which translates
that port's result into this narrower shape, so this module never imports
across ``reconciliation``'s own boundary for it."""


class FakeVenueBook:
    def __init__(self, ledger_reader: PoolLedgerReader) -> None:
        self._ledger_reader = ledger_reader
        self._nets: dict[tuple[str, str], Decimal] = {}
        self._seeded_pools: set[_PoolKey] = set()

    async def open_positions(self, pool: _PoolKey) -> list[tuple[str, Decimal]]:
        """Every market this pool's book currently knows about -- seeding
        from the ledger the first time this EXACT pool is asked about, never
        again after that."""
        exchange = pool[0]
        if pool not in self._seeded_pools:
            for symbol, net_base in await self._ledger_reader(pool):
                key = (exchange, strip_contract_marker(symbol).upper())
                self._nets.setdefault(key, net_base)
            self._seeded_pools.add(pool)

        return [
            (market, net) for (exch, market), net in self._nets.items() if exch == exchange
        ]

    def record_fill(self, exchange: str, symbol: str, delta: Decimal) -> None:
        """Called by ``FakeExchangeAdapter`` when a fill it produced becomes
        visible. ``delta`` is the SIGNED base quantity change -- positive for
        a BUY, negative for a SELL."""
        key = (exchange, strip_contract_marker(symbol).upper())
        self._nets[key] = self._nets.get(key, Decimal("0")) + delta

    def inject(self, exchange: str, symbol: str, delta: Decimal) -> None:
        """Test-only: manufactures a venue-side move ``FakeExchangeAdapter``
        never produced -- a manual close or a liquidation -- so a GHOST or
        AMBIGUOUS classification can be rehearsed under DRY_RUN without a
        real venue. Never called from production code."""
        self.record_fill(exchange, symbol, delta)
