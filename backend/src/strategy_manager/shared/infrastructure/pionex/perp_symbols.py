"""Per-contract trading rules for perpetual markets, and the rounding they
force on every futures order.

The spot equivalent lives in ``symbols.py`` and this is deliberately its
sibling rather than an extension of it: the two report different fields, and
the futures table adds a constraint spot does not have at all.

Verified 2026-08-24 against the live account. ``GET /api/v1/common/symbols``
with ``type=PERP`` reports, for ``BTC_USDT_PERP``::

    basePrecision: 4      baseStep: 0.0001
    minNotional:   1      minSizeMarket: 0.0001   maxSizeMarket: 100

**Rounding is to the STEP, not to the precision.** They agree on every
contract observed so far -- ``basePrecision: 4`` and ``baseStep: 0.0001`` say
the same thing for BTC -- but they are not the same rule. A step of
``0.0005`` would pass a precision check at four decimals and still be
rejected. The step is what the venue actually enforces, so it is what is
enforced here.

And it always rounds DOWN, for the reason ``symbols.py`` gives at length:
rounding a size up spends capital the allocation engine never granted, and on
a close asks the venue to reduce more than the position holds. Down leaves
dust; up invents money.

**``maxSizeMarket`` has no spot counterpart.** A market order above it is
rejected outright. Because a futures size is ``granted * leverage / price``,
the leverage multiplier makes hitting a ceiling far easier than on spot -- at
100x, a grant a hundredth of the size does it. Refusing here names the number
and the limit instead of letting an opaque rejection code come back.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

SYMBOLS_PATH = "/api/v1/common/symbols"
PERP = "PERP"

TRADING = "TRADING"


@dataclass(frozen=True, slots=True)
class PerpRules:
    """One perpetual market's order constraints, as Pionex reports them."""

    symbol: str
    base_precision: int
    base_step: Decimal
    min_notional: Decimal
    min_size_market: Decimal
    max_size_market: Decimal
    status: str

    def round_base_size(self, size: Decimal) -> Decimal:
        """Truncates to the venue's step, downward.

        Falls back to the declared precision when the step is not a usable
        divisor, so a malformed or zero step degrades to the weaker check
        rather than raising a ``DivisionByZero`` from inside an order path.
        """
        if self.base_step > 0:
            steps = (size / self.base_step).to_integral_value(rounding=ROUND_DOWN)
            return steps * self.base_step
        return size.quantize(
            Decimal(1).scaleb(-self.base_precision), rounding=ROUND_DOWN
        )

    def assert_tradable(self, size: Decimal, price: Decimal) -> None:
        """Every constraint that decides whether this order is placeable.

        Checked together and named individually, because the operator's
        remedy differs for each: a size below the floor needs a bigger grant,
        one above the ceiling needs a smaller one or less leverage, and an
        offline market needs a different symbol entirely.
        """
        if self.status.upper() != TRADING:
            raise PionexApiError(
                f"{self.symbol} is {self.status}, not {TRADING}; it cannot be traded"
            )
        if size < self.min_size_market:
            raise PionexApiError(
                f"{self.symbol} requires a market order of at least "
                f"{self.min_size_market} in the base currency; this one is {size}"
            )
        if size > self.max_size_market:
            raise PionexApiError(
                f"{self.symbol} caps a market order at {self.max_size_market} in "
                f"the base currency; this one is {size}"
            )

        notional = size * price
        if notional < self.min_notional:
            raise PionexApiError(
                f"{self.symbol} requires a notional of at least "
                f"{self.min_notional}; this one is {notional} "
                f"({size} at {price})"
            )


class PionexPerpCatalog:
    """Fetches the perpetual contract table once and answers from memory.

    Cached per instance and the trade client is built per job, so this costs
    one extra GET on a job about to place an order -- the right trade for
    numbers that decide whether the order is accepted at all.

    Note the path: the perpetual catalogue is served from the SPOT common
    namespace with ``type=PERP``, not from ``/uapi/v1/``. Assuming the futures
    base path here returns a 404 on every lookup.
    """

    def __init__(self, transport: PionexTransport) -> None:
        self._transport = transport
        self._rules: dict[str, PerpRules] | None = None

    async def rules_for(self, symbol: str) -> PerpRules:
        if self._rules is None:
            self._rules = await self._load()

        rules = self._rules.get(symbol.upper())
        if rules is None:
            raise PionexApiError(
                f"Pionex does not list {symbol!r} as a perpetual market"
            )
        return rules

    async def _load(self) -> dict[str, PerpRules]:
        data = await self._transport.get(SYMBOLS_PATH, {"type": PERP})
        symbols = data.get("symbols") if isinstance(data, dict) else None
        if not isinstance(symbols, list):
            raise PionexApiError(
                "perpetual symbols payload is not a list; got "
                f"{type(symbols).__name__}"
            )

        return {
            entry["symbol"].upper(): _parse(entry)
            for entry in symbols
            if isinstance(entry, dict) and isinstance(entry.get("symbol"), str)
        }


def _parse(entry: dict[str, Any]) -> PerpRules:
    return PerpRules(
        symbol=str(entry["symbol"]).upper(),
        base_precision=_int(entry, "basePrecision"),
        base_step=_amount(entry, "baseStep"),
        min_notional=_amount(entry, "minNotional"),
        min_size_market=_amount(entry, "minSizeMarket"),
        max_size_market=_amount(entry, "maxSizeMarket"),
        status=_str(entry, "status"),
    )


def _str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        raise PionexApiError(f"perp.{field} must be a non-empty string, got {value!r}")
    return value


def _int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PionexApiError(
            f"perp.{field} must be an integer, got {type(value).__name__}"
        )
    if value < 0:
        raise PionexApiError(f"perp.{field} must not be negative, got {value}")
    return value


def _amount(entry: dict[str, Any], field: str) -> Decimal:
    value = entry.get(field)
    if not isinstance(value, str):
        raise PionexApiError(
            f"perp.{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"perp.{field} is not a valid decimal: {value!r}") from exc
