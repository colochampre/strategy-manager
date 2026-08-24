"""One Pionex fill, and the parsing that turns a wire payload into it.

Shared by the spot and futures trade clients because the payload is the same
on both. That is not an assumption: the futures ``Fill`` model documents the
identical field set -- ``id``, ``orderId``, ``symbol``, ``side``, ``price``,
``size``, ``fee``, ``feeCoin``, ``timestamp`` -- adding only ``role`` and
``feeType``, neither of which this system reads.

The spot shape was verified against real fills on 2026-08-24, including the
detail that matters most and is easiest to get wrong: **the fee changes
currency with the side.** A buy is charged in the base currency, a sell in the
quote. ``feeCoin`` is therefore never redundant with the symbol, and a close
sized without accounting for a base-currency fee asks to sell more than
arrived.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError


@dataclass(frozen=True, slots=True)
class PionexFill:
    """One fill record, a straight transcription of the wire payload.

    Amounts stay ``Decimal`` parsed from the string Pionex sent. Mapping this
    onto the ledger's own ``Fill`` is a separate, testable decision made in
    ``execution.infrastructure.pionex_exchange``.
    """

    fill_id: str
    order_id: str
    symbol: str
    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    fee_coin: str
    timestamp_ms: int

def parse_fills(data: Any) -> list[PionexFill]:
    """Turns a fills payload into fill records."""
    return [_parse_fill(entry) for entry in _fill_entries(data)]


def _fill_entries(data: Any) -> list[Any]:
    """Accepts either shape Pionex might use.

    The balances endpoint wraps its list as ``{"balances": [...]}``, so a
    ``fills`` key is the shape to expect here -- but that has not been
    confirmed against a live fill, and a bare list is the other plausible
    reading. Accepting both is cheap; guessing wrong and raising on a real
    fill is not.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        fills = data.get("fills")
        if isinstance(fills, list):
            return fills
    raise PionexApiError("fills payload is neither a list nor an object with fills")


def _parse_fill(entry: Any) -> PionexFill:
    if not isinstance(entry, dict):
        raise PionexApiError("fill entry is not an object")

    return PionexFill(
        fill_id=_require_str(entry, "id"),
        order_id=_require_str(entry, "orderId"),
        symbol=_require_str(entry, "symbol"),
        side=_require_str(entry, "side"),
        price=_amount(entry, "price"),
        size=_amount(entry, "size"),
        fee=_amount(entry, "fee"),
        fee_coin=_require_str(entry, "feeCoin"),
        timestamp_ms=_require_int(entry, "timestamp"),
    )


def _require_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if value is None or value == "":
        raise PionexApiError(f"fill entry has no {field}")
    return str(value)


def _require_int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int):
        raise PionexApiError(
            f"fill.{field} must be an integer, got {type(value).__name__}"
        )
    return value


def _amount(entry: dict[str, Any], field: str) -> Decimal:
    """Same rule as the balance reader: a JSON number has already lost
    precision before it reaches us, so it is rejected rather than coerced.
    This is a fill price -- it lands in the append-only ledger and can never
    be corrected there.
    """
    value = entry.get(field)
    if not isinstance(value, str):
        raise PionexApiError(
            f"fill.{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"fill.{field} is not a valid decimal: {value!r}") from exc
