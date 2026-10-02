"""Which USDⓈ-M perpetuals Binance lists, read WITHOUT a key.

The API process uses this to validate the pairs a strategy may trade. It
builds on :class:`BinancePublicTransport`, which cannot sign, so this module
has no credential to leak and no way to authenticate. ``/fapi/v1/exchangeInfo``
answers without a signature or a key header from the VPS (probe P7).

**One filter, shared with the order path.** Each entry is parsed with
``parse_contract`` and kept when ``is_perpetual and is_trading and
settles_in(currency)``. Those are the properties ``assert_tradable`` checks
before every order, so "available" means "the order path could parse this
market and would not refuse it". ``contractType == "PERPETUAL"`` already
excludes ``TRADIFI_PERPETUAL`` and the dated quarterlies; the MARGIN asset, not
the quote asset, decides the pool. The symbol text is never the criterion.

**HTTP 451 is an error, never an empty listing.** Binance answers it for the
location the request comes from, and an empty list would make every save look
like a typo. The transport raises it and this module lets it through.

**What fails here without a log line?** Nothing is dropped quietly:

* an entry that does not parse is skipped, and ONE warning per read names the
  count and up to ten symbols;
* a non-empty listing that leaves no available pair is not an empty answer, it
  is an unreadable one, so it raises and logs one error naming the values that
  arrived.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Final

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import (
    EXCHANGE_INFO_PATH,
    PerpContract,
    parse_contract,
)
from strategy_manager.shared.infrastructure.binance.transport import (
    BinancePublicTransport,
)

logger = logging.getLogger(__name__)

_NO_SYMBOL: Final = "<no symbol>"
_SYMBOLS_NAMED: Final = 10


class BinancePublicCatalogue:
    """Reads the USDⓈ-M ``exchangeInfo`` listing and filters it for one pool."""

    def __init__(
        self,
        transport: BinancePublicTransport,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._monotonic = monotonic

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]:
        """Venue-spelled symbols of every trading perpetual margined in
        ``settlement_currency``, in the order Binance listed them.

        Raises ``BinanceApiError`` when the venue cannot be read (HTTP 451
        included) and when a non-empty listing yields no available pair.
        """
        started = self._monotonic()
        entries = await self._read_listing()

        contracts: list[PerpContract] = []
        skipped: list[str] = []
        for entry in entries:
            try:
                contracts.append(parse_contract(entry))
            except BinanceApiError:
                skipped.append(_symbol_of(entry))

        if skipped:
            logger.warning(
                "binance usdt-m catalogue: skipped %d malformed entries, treated as "
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
                "binance usdt-m catalogue: %d entries listed but none is an available "
                "%s perpetual; the filter may no longer match the venue. contract "
                "types seen: %s; statuses seen: %s; margin assets seen: %s; "
                "skipped: %d",
                len(entries),
                settlement_currency,
                _seen(c.contract_type for c in contracts),
                _seen(c.status for c in contracts),
                _seen(c.margin_asset for c in contracts),
                len(skipped),
            )
            raise BinanceApiError(
                f"the exchangeInfo catalogue lists {len(entries)} entries but no "
                f"tradable perpetual margined in {settlement_currency}"
            )

        logger.info(
            "binance usdt-m catalogue read: settlement_currency=%s listed=%d "
            "available=%d skipped=%d elapsed_ms=%d",
            settlement_currency,
            len(entries),
            len(available),
            len(skipped),
            round((self._monotonic() - started) * 1000),
        )
        return available

    async def _read_listing(self) -> list[Any]:
        payload = await self._transport.get(EXCHANGE_INFO_PATH)
        if not isinstance(payload, dict):
            raise BinanceApiError(f"{EXCHANGE_INFO_PATH} returned a non-object body")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list):
            raise BinanceApiError(f"{EXCHANGE_INFO_PATH} returned no 'symbols' list")
        return symbols


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
