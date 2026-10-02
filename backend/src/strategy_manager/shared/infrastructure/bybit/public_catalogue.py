"""Which linear perpetuals Bybit lists, read WITHOUT a key.

The API process uses this to validate the pairs a strategy may trade. It
builds on :class:`BybitPublicTransport`, which cannot sign, so this module has
no credential to leak and no way to authenticate.

**One filter, shared with the order path.** Each entry is parsed with
``parse_contract`` and kept when ``is_perpetual and is_trading and
settles_in(currency)``. Those are the very properties ``assert_tradable``
checks before every order, so "available" means "the order path could parse
this market and would not refuse it". The symbol text is never the criterion:
``BTCUSDT-25DEC26`` is out because it is a ``LinearFutures``, not because of
its suffix.

**It cannot silently truncate.** The cursor is followed until Bybit returns an
empty one. Bybit ends its last page with an EMPTY ``nextPageCursor`` rather
than an absent field (probe P7, 2026-10-02), and an absent field must end the
read too. A page cap raises rather than returning a partial list, because a
list missing its tail turns valid pairs into "unknown" ones.

**What fails here without a log line?** Nothing is dropped quietly:

* an entry that does not parse is skipped, and ONE warning per read names the
  count and up to ten symbols;
* a non-empty listing that leaves no available pair is not an empty answer, it
  is an unreadable one (Pionex's documented ``contractType`` was really
  ``type``), so it raises and logs one error naming the values that arrived.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Final

from strategy_manager.shared.infrastructure.bybit.catalogue_pages import (
    LINEAR,
    MAX_PAGES,
    PAGE_LIMIT,
    read_every_page,
)
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import (
    PerpContract,
    parse_contract,
)
from strategy_manager.shared.infrastructure.bybit.transport import (
    BybitPublicTransport,
)

logger = logging.getLogger(__name__)

__all__ = ["MAX_PAGES", "PAGE_LIMIT", "BybitPublicCatalogue"]

_NO_SYMBOL: Final = "<no symbol>"
_SYMBOLS_NAMED: Final = 10


class BybitPublicCatalogue:
    """Reads the ``linear`` instrument listing and filters it for one pool."""

    def __init__(
        self,
        transport: BybitPublicTransport,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._monotonic = monotonic

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]:
        """Venue-spelled symbols of every trading perpetual settled in
        ``settlement_currency``, in the order Bybit listed them.

        Raises ``BybitApiError`` when the venue cannot be read, when the
        listing does not end within ``MAX_PAGES`` pages, and when a non-empty
        listing yields no available pair.
        """
        started = self._monotonic()
        entries, pages = await self._read_every_page()

        contracts: list[PerpContract] = []
        skipped: list[str] = []
        for entry in entries:
            try:
                contracts.append(parse_contract(entry))
            except BybitApiError:
                skipped.append(_symbol_of(entry))

        if skipped:
            logger.warning(
                "bybit linear catalogue: skipped %d malformed entries, treated as "
                "not available (symbols: %s)",
                len(skipped),
                ", ".join(skipped[:_SYMBOLS_NAMED]),
            )

        available = tuple(
            contract.symbol
            for contract in contracts
            if contract.is_perpetual
            and contract.is_trading
            and contract.settles_in(settlement_currency)
        )

        if entries and not available:
            logger.error(
                "bybit linear catalogue: %d entries listed but none is an available "
                "%s perpetual; the filter may no longer match the venue. contract "
                "types seen: %s; statuses seen: %s; settle coins seen: %s; "
                "skipped: %d",
                len(entries),
                settlement_currency,
                _seen(c.contract_type for c in contracts),
                _seen(c.status for c in contracts),
                _seen(c.settle_coin for c in contracts),
                len(skipped),
            )
            raise BybitApiError(
                f"the {LINEAR} catalogue lists {len(entries)} entries but no tradable "
                f"perpetual settled in {settlement_currency}"
            )

        logger.info(
            "bybit linear catalogue read: settlement_currency=%s listed=%d "
            "available=%d skipped=%d pages=%d elapsed_ms=%d",
            settlement_currency,
            len(entries),
            len(available),
            len(skipped),
            pages,
            round((self._monotonic() - started) * 1000),
        )
        return available

    async def _read_every_page(self) -> tuple[list[Any], int]:
        return await read_every_page(self._transport.get)


def _symbol_of(entry: Any) -> str:
    """The entry's symbol for a log line, or a marker when even that is gone.
    Never the payload: a malformed entry is named, not dumped."""
    if isinstance(entry, dict):
        symbol = entry.get("symbol")
        if isinstance(symbol, str) and symbol:
            return symbol
    return _NO_SYMBOL


def _seen(values: Any) -> str:
    return ", ".join(sorted(set(values))) or "none"
