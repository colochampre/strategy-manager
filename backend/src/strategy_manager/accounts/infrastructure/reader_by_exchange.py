"""``ReaderByExchange``: implements ``ExchangeBalanceReaderPort`` by routing a
read to whichever exchange's reader is registered for the pool being asked
about -- built LAZILY, from a factory, the first time that exchange is
actually requested.

Exists so ``handle_signal_process`` (main.py) can build ONE
``RefreshPoolBalance`` per job, capable of refreshing any configured
exchange's pool -- but ``RefreshPoolBalance`` is only ever asked for the one
pool the signal being processed actually belongs to (design.md § S3), never
every pool the exchange holds, and often (every RELEASES signal, every
CONSUMES signal that never reaches the refresh) for no pool at all.

Laziness is not an optimization here, it is a correctness requirement
(design.md § S3 correction, 2026-09-21): a factory represents a credential
decrypt plus an HTTP client open, and building both exchanges' factories
eagerly would cost a close -- or a signal on one exchange -- a credential
problem it never needed, exactly what ``main.py``'s ``exchange_for`` already
guards against for trade clients (``_vault_credential``: "A Binance key
nobody has sealed must cost Binance signals and nothing else"). A factory
that raises is left to propagate rather than being swallowed here, so
``RefreshPoolBalance`` -- the only caller -- can catch it and degrade through
FALLBACK/UNAVAILABLE exactly like any other reader failure; it must never
raise out of job entry.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from strategy_manager.accounts.application.ports import (
    ExchangeBalanceReaderPort,
    PoolBalanceReading,
    PoolKey,
)

ReaderFactory = Callable[[], Awaitable[ExchangeBalanceReaderPort]]


class ReaderByExchange:
    def __init__(self, factories: Mapping[str, ReaderFactory]) -> None:
        self._factories = factories
        self._built: dict[str, ExchangeBalanceReaderPort] = {}

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        exchange = pools[0][0]
        reader = await self._reader_for(exchange)
        return await reader.read(pools)

    async def _reader_for(self, exchange: str) -> ExchangeBalanceReaderPort:
        built = self._built.get(exchange)
        if built is not None:
            return built

        factory = self._factories.get(exchange)
        if factory is None:
            raise ValueError(
                f"no balance reader registered for exchange {exchange!r}; configured "
                f"exchanges are {sorted(self._factories)}"
            )
        reader = await factory()
        self._built[exchange] = reader
        return reader
