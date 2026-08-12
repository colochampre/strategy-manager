"""TradingView alert parsing and idempotency-key derivation.

The alert body is the owner's existing Pionex-format TradingView alert,
adopted unchanged so the same alert can keep feeding Pionex signal bots
during migration (design.md § "Alert Contract and Signal Routing"):

    {"data":{"action":"{{strategy.order.action}}",
              "contracts":"{{strategy.order.contracts}}",
              "position_size":"{{strategy.position_size}}"},
     "price":"{{close}}","signal_param":"{}",
     "signal_type":"<per-strategy uuid>","symbol":"{{ticker}}",
     "time":"{{timenow}}"}

Every numeric field arrives as a string; this module is the single place
that coerces it to ``Decimal``. No framework imports, per the layering rule.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from strategy_manager.shared.domain.errors import DomainError


class AlertParsingError(DomainError):
    """Raised when a webhook payload does not match the expected alert shape."""


@dataclass(frozen=True, slots=True)
class TradingViewAlert:
    """A parsed TradingView alert. ``contracts`` is diagnostic only — see
    design.md § "Order size never comes from the alert"."""

    action: str
    contracts: Decimal
    position_size: Decimal
    price: Decimal
    symbol: str
    signal_type: str
    time: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TradingViewAlert":
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AlertParsingError("payload is missing a 'data' object")

        try:
            action = data["action"]
            contracts = _to_decimal(data["contracts"], "data.contracts")
            position_size = _to_decimal(data["position_size"], "data.position_size")
            price = _to_decimal(payload["price"], "price")
            symbol = payload["symbol"]
            signal_type = payload["signal_type"]
            time = payload["time"]
        except KeyError as exc:
            raise AlertParsingError(f"payload is missing required field {exc}") from exc

        _require_non_empty_str(action, "data.action")
        _require_non_empty_str(symbol, "symbol")
        _require_non_empty_str(signal_type, "signal_type")
        _require_non_empty_str(time, "time")

        return cls(
            action=action,
            contracts=contracts,
            position_size=position_size,
            price=price,
            symbol=symbol,
            signal_type=signal_type,
            time=time,
        )


def _to_decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise AlertParsingError(f"{field} must be a string, got {type(value).__name__}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise AlertParsingError(f"{field} is not a valid decimal string: {value!r}") from exc


def _require_non_empty_str(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise AlertParsingError(f"{field} must be a non-empty string")


def derive_idempotency_key(alert: TradingViewAlert) -> str:
    """``key = hash(signal_type + time + action + contracts + position_size)``.

    ``time`` alone is insufficient: it has only second resolution
    (``{{timenow}}``), so two genuinely different signals fired within the
    same second would otherwise collide (design.md § "Idempotency key").
    """

    raw = f"{alert.signal_type}|{alert.time}|{alert.action}|{alert.contracts}|{alert.position_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
