"""How numbers and instants are written on the admin API's wire.

**Money, quantities and ratios are JSON strings, never JSON numbers.** A JSON
number is read as a binary float by most clients, and a float cannot hold
``0.1`` exactly. Nothing that moves or reports money may be rounded by the
transport.

**Plain notation.** ``str(Decimal)`` is not stable: ``Decimal("100.000000000000000000")
- Decimal("100.000000000000000000")`` prints as ``"0E-18"``. A client that
parses that string with a decimal library may accept it and one that pattern-
matches digits will not, so every ``Decimal`` here is written with
``format(value, "f")``. A negative zero is written as zero.

``Ratio`` additionally rounds to 10 places (design.md section 11: "ratios are
quantized to 10 places on the wire"), half-even, in a context wide enough that
the rounding itself can never raise.

``Price`` is the type of a price that is a quotient (``notional / quantity``,
computed in a wider context than the wire's). It rounds to 18 places, half-even:
the ledger's own scale, so a price taken from one fill reads as that fill's price.
It is written in plain notation like the others.

**Instants.** ``Instant`` is timezone-aware and written in UTC (pydantic writes
a zero offset as ``Z``). A naive datetime is refused rather than assumed to be
UTC.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated

from pydantic import AfterValidator, PlainSerializer

_RATIO_PLACES = Decimal("1e-10")
_PRICE_PLACES = Decimal("1e-18")


def plain(value: Decimal) -> str:
    """``value`` in positional notation, with no exponent and no ``-0``."""
    text = format(value, "f")
    return text[1:] if value == 0 and text.startswith("-") else text


def ratio(value: Decimal) -> str:
    """``value`` rounded to 10 places and written in positional notation."""
    with localcontext() as context:
        context.prec = 80
        return plain(value.quantize(_RATIO_PLACES, rounding=ROUND_HALF_EVEN))


def price(value: Decimal) -> str:
    """``value`` rounded to 18 places and written in positional notation."""
    with localcontext() as context:
        context.prec = 80
        return plain(value.quantize(_PRICE_PLACES, rounding=ROUND_HALF_EVEN))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{value.isoformat()} has no time zone; it is not an instant")
    return value.astimezone(UTC)


Money = Annotated[Decimal, PlainSerializer(plain, return_type=str, when_used="json")]
Ratio = Annotated[Decimal, PlainSerializer(ratio, return_type=str, when_used="json")]
Price = Annotated[Decimal, PlainSerializer(price, return_type=str, when_used="json")]
Instant = Annotated[datetime, AfterValidator(_utc)]
