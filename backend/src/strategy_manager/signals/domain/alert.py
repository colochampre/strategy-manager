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
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import Any

from strategy_manager.shared.domain.errors import DomainError

# What the ``signals`` table can hold in each numeric column: migration 0002
# declares price, contracts and position_size as NUMERIC(38, 18). A value the
# column refuses is refused here, as a bad request, instead of at the insert,
# where nothing catches it and the webhook answers an unhandled 500.
_STORED_SCALE = 18
_STORED_INTEGER_DIGITS = 20
_STORED_LIMIT = Decimal(10) ** _STORED_INTEGER_DIGITS
_STORED_QUANTUM = Decimal(1).scaleb(-_STORED_SCALE)
_MAX_EXPONENT = 16383
# Wide enough to round any value that passes the exponent check below, and
# rounding half away from zero like PostgreSQL does when it stores the number.
_STORED_CONTEXT = Context(prec=60, rounding=ROUND_HALF_UP)


class AlertParsingError(DomainError):
    """Raised when a webhook payload does not match the expected alert shape.

    The message is the 422 detail and some of them repeat the value the sender
    supplied, so it must never reach a log. ``field`` and ``reason`` are the safe
    account of the same refusal: a field name and a fixed phrase from this
    module, never a value. ``log_text`` is built from those two alone.
    """

    def __init__(self, message: str, *, field: str, reason: str) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason

    @property
    def log_text(self) -> str:
        return f"{self.field} {self.reason}"


class NonFiniteNumberError(AlertParsingError):
    """A numeric field is NaN or infinite. Carries the field name, never the value."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"{field} is not a finite number", field=field, reason="is not a finite number"
        )


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
    def from_payload(cls, payload: Any) -> "TradingViewAlert":
        if not isinstance(payload, dict):
            # Valid JSON is not necessarily an object: a list, a string, a
            # number and ``null`` all parse. Nothing of it is echoed back.
            raise AlertParsingError(
                "payload is not a JSON object", field="body", reason="is not a JSON object"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AlertParsingError(
                "payload is missing a 'data' object",
                field="data",
                reason="is missing or not an object",
            )

        action = _required(data, "action", "data.action")
        contracts = _to_decimal(_required(data, "contracts", "data.contracts"), "data.contracts")
        position_size = _to_decimal(
            _required(data, "position_size", "data.position_size"), "data.position_size"
        )
        price = _to_decimal(_required(payload, "price", "price"), "price", positive=True)
        symbol = _required(payload, "symbol", "symbol")
        signal_type = _required(payload, "signal_type", "signal_type")
        time = _required(payload, "time", "time")

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


def _to_decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    """Coerce one numeric string, refusing what the ``signals`` table would.

    ``positive`` is the CHECK ``price > 0`` of migration 0002, and the only sign
    rule the database has: a closing alert carries a ``position_size`` of zero
    and a short position may carry a negative one, so ``contracts`` and
    ``position_size`` accept any finite number that fits the column.
    """

    if not isinstance(value, str):
        raise AlertParsingError(
            f"{field} must be a string, got {type(value).__name__}",
            field=field,
            reason="is not a string",
        )
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        # The detail echoes the value, as it always did; the log text does not.
        raise AlertParsingError(
            f"{field} is not a valid decimal string: {value!r}",
            field=field,
            reason="is not a valid decimal string",
        ) from exc
    if not number.is_finite():
        # ``Decimal`` accepts NaN, sNaN and every spelling of infinity without
        # raising. The raw value is deliberately not echoed back.
        raise NonFiniteNumberError(field)
    if positive and number <= 0:
        raise _not_above_zero(field)
    # Checked on the exponent first, so a value like ``1E+999999`` is refused
    # without ever being expanded into its digits. The exponent bound is
    # PostgreSQL's: NUMERIC cannot receive a display scale above 16383, so
    # ``1E-20000`` and ``0E+999999`` are refused at the insert although they are
    # finite, and a zero is no exception.
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or abs(exponent) > _MAX_EXPONENT:
        raise _out_of_range(field)
    if number and number.adjusted() >= _STORED_INTEGER_DIGITS:
        raise _out_of_range(field)
    stored = number.quantize(_STORED_QUANTUM, context=_STORED_CONTEXT)
    if abs(stored) >= _STORED_LIMIT:
        # Rounding to 18 decimals carried it past the column's last integer digit.
        raise _out_of_range(field)
    if positive and stored <= 0:
        # Above zero as sent, zero as stored: the CHECK would refuse it.
        raise _not_above_zero(field)
    return number


def _not_above_zero(field: str) -> AlertParsingError:
    return AlertParsingError(
        f"{field} must be above zero", field=field, reason="is not above zero"
    )


def _out_of_range(field: str) -> AlertParsingError:
    return AlertParsingError(
        f"{field} is out of range for the stored precision",
        field=field,
        reason="is out of range for the stored precision",
    )


def _required(mapping: dict[str, Any], key: str, field: str) -> Any:
    try:
        return mapping[key]
    except KeyError as exc:
        raise AlertParsingError(
            f"payload is missing required field '{key}'", field=field, reason="is missing"
        ) from exc


def _require_non_empty_str(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise AlertParsingError(
            f"{field} must be a non-empty string", field=field, reason="is empty or not a string"
        )


def derive_idempotency_key(alert: TradingViewAlert) -> str:
    """``key = hash(signal_type + time + action + contracts + position_size)``.

    ``time`` alone is insufficient: it has only second resolution
    (``{{timenow}}``), so two genuinely different signals fired within the
    same second would otherwise collide (design.md § "Idempotency key").
    """

    raw = f"{alert.signal_type}|{alert.time}|{alert.action}|{alert.contracts}|{alert.position_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
