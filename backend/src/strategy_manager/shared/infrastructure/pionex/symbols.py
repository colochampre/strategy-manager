"""Per-symbol trading rules, and the rounding they force on every order.

Verified 2026-08-24 against the live account. ``GET /api/v1/common/symbols``
reports, for ``ETH_USDT``::

    basePrecision: 5      amountPrecision: 8
    minTradeSize: 0.00001 minAmount: 10

Those four numbers are not advisory. An order violating any of them is
rejected, and both legs of a round trip violate them by default:

**The buy.** ``amount`` is the reservation's granted capital, which is a
percentage of an exchange balance — and Pionex reports balances with far more
precision than it accepts on an order. A live spot balance of
``901.05606580776785293876389408`` USDT taken at any percentage produces an
amount with more than eight decimals. Every buy would be refused.

**The sell.** ``base_size`` comes from the ledger as bought minus
base-currency fees, which carries whatever precision the fills had. ETH allows
five decimals. Every sell would be refused.

So the adapter rounds, and it rounds DOWN on both legs, always. Rounding a buy
up would spend capital the allocation engine never granted. Rounding a sell up
would try to sell more of the base currency than the account holds, which the
exchange refuses for insufficient balance — the one failure mode that leaves a
position open while the system believes it closed. Down leaves dust; up
invents money.

Below the minimum, the order is refused here rather than sent. Pionex would
reject it anyway, but locally the failure names the actual number and the
actual limit instead of arriving as an opaque rejection code.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

SYMBOLS_PATH = "/api/v1/common/symbols"
SPOT = "SPOT"


@dataclass(frozen=True, slots=True)
class SymbolRules:
    """One market's order constraints, as Pionex reports them."""

    symbol: str
    base_precision: int
    amount_precision: int
    min_trade_size: Decimal
    min_amount: Decimal

    def round_amount(self, amount: Decimal) -> Decimal:
        """Quote amount for a market BUY, truncated to what Pionex accepts."""
        return _floor_to(amount, self.amount_precision)

    def round_base_size(self, size: Decimal) -> Decimal:
        """Base size for a market SELL, truncated to what Pionex accepts."""
        return _floor_to(size, self.base_precision)

    def assert_amount_tradable(self, amount: Decimal) -> None:
        if amount < self.min_amount:
            raise PionexApiError(
                f"{self.symbol} requires an order of at least {self.min_amount} "
                f"in the quote currency; this one is {amount}"
            )

    def assert_size_tradable(self, size: Decimal) -> None:
        if size < self.min_trade_size:
            raise PionexApiError(
                f"{self.symbol} requires an order of at least "
                f"{self.min_trade_size} in the base currency; this one is {size}"
            )


class PionexSymbolCatalog:
    """Fetches the spot symbol table once and answers from memory after that.

    Cached per instance, and the trade client is built per job, so this costs
    one extra GET on a job that is about to place an order. That is the right
    trade for numbers that decide whether the order is accepted at all: a
    stale cached precision produces a rejection nobody can explain from the
    logs.
    """

    def __init__(self, transport: PionexTransport) -> None:
        self._transport = transport
        self._rules: dict[str, SymbolRules] | None = None

    async def rules_for(self, symbol: str) -> SymbolRules:
        if self._rules is None:
            self._rules = await self._load()

        rules = self._rules.get(symbol.upper())
        if rules is None:
            raise PionexApiError(
                f"Pionex does not list {symbol!r} as a tradable spot market"
            )
        return rules

    async def _load(self) -> dict[str, SymbolRules]:
        data = await self._transport.get(SYMBOLS_PATH, {"type": SPOT})
        symbols = data.get("symbols") if isinstance(data, dict) else None
        if not isinstance(symbols, list):
            raise PionexApiError("symbols payload is not a list")

        return {
            entry["symbol"].upper(): _parse(entry)
            for entry in symbols
            if isinstance(entry, dict) and isinstance(entry.get("symbol"), str)
        }


def _parse(entry: dict[str, Any]) -> SymbolRules:
    return SymbolRules(
        symbol=str(entry["symbol"]).upper(),
        base_precision=_int(entry, "basePrecision"),
        amount_precision=_int(entry, "amountPrecision"),
        min_trade_size=_amount(entry, "minTradeSize"),
        min_amount=_amount(entry, "minAmount"),
    )


def _int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int):
        raise PionexApiError(
            f"symbol.{field} must be an integer, got {type(value).__name__}"
        )
    if value < 0:
        raise PionexApiError(f"symbol.{field} must not be negative, got {value}")
    return value


def _amount(entry: dict[str, Any], field: str) -> Decimal:
    value = entry.get(field)
    if not isinstance(value, str):
        raise PionexApiError(
            f"symbol.{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"symbol.{field} is not a valid decimal: {value!r}") from exc


def _floor_to(value: Decimal, places: int) -> Decimal:
    """Truncate toward zero at ``places`` decimals.

    ``ROUND_DOWN`` in ``decimal`` means toward zero, which for the positive
    quantities this handles is exactly "never more than we had".
    """
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
