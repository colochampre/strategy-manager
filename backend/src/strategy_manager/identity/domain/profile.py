"""The identity a user gives at sign-up (openspec/changes/public-site, LS2-LS3).

First name, last name, CUIT and country: what lets the owner say whose trades
these are if an authority asks (LD1). None of it is proven, only declared, and
the rules here only refuse what cannot be true:

- **The CUIT** (or CUIL) is eleven digits, the last one the check digit AFIP
  computes from the first ten. Hyphens and spaces are how people write it and are
  dropped; anything else is refused, ASCII digits only, so ``٢٠`` is no ``20``.
- **A name** is trimmed and its inner whitespace folds to one space; it keeps its
  case and accents. Empty, longer than ``NAME_MAX_LENGTH`` or holding a character
  nobody can see (the display name's own rule) is refused.
- **The country** is Argentina only (LS1). It is checked first: someone abroad
  hears that the service is not offered to them, not that a field is wrong.
"""

import re
import unicodedata
from dataclasses import dataclass

from strategy_manager.identity.domain.display_name import is_invisible

SERVED_COUNTRY = "AR"
NAME_MAX_LENGTH = 80

_CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_CUIT_SHAPE = re.compile(r"[0-9]{11}")


class InvalidProfileError(ValueError):
    """One field cannot be what it claims; ``field`` names it as the API does."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class CountryNotServedError(ValueError):
    """The service is offered only to residents of Argentina for now (LS2)."""


def cuit_check_digit(first_ten: str) -> int | None:
    """AFIP's check digit for ``first_ten``: 11 minus the weighted sum modulo 11,
    0 when the remainder is 0. A remainder of 1 has no digit, so ``None``: AFIP
    never issues such a number."""
    remainder = sum(int(d) * w for d, w in zip(first_ten, _CUIT_WEIGHTS, strict=True)) % 11
    if remainder == 0:
        return 0
    if remainder == 1:
        return None
    return 11 - remainder


def normalize_cuit(raw: str) -> str:
    digits = re.sub(r"[\s-]", "", raw)
    if not _CUIT_SHAPE.fullmatch(digits):
        raise InvalidProfileError("cuit", "a CUIT is eleven digits")
    if cuit_check_digit(digits[:10]) != int(digits[10]):
        raise InvalidProfileError("cuit", "the CUIT's check digit does not match")
    return digits


def normalize_person_name(raw: str, field: str) -> str:
    name = " ".join(unicodedata.normalize("NFC", raw).split())
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise InvalidProfileError(field, f"a name has 1 to {NAME_MAX_LENGTH} characters")
    if any(is_invisible(character) for character in name):
        raise InvalidProfileError(field, "a name holds no invisible characters")
    return name


@dataclass(frozen=True)
class Profile:
    first_name: str
    last_name: str
    cuit: str
    country: str

    @classmethod
    def of(cls, *, first_name: str, last_name: str, cuit: str, country: str) -> "Profile":
        """The normal spellings, or ``CountryNotServedError`` before any other
        refusal, or ``InvalidProfileError`` naming the first wrong field."""
        if country.strip().upper() != SERVED_COUNTRY:
            raise CountryNotServedError(
                "The service is offered only to residents of Argentina for now."
            )
        return cls(
            first_name=normalize_person_name(first_name, "first_name"),
            last_name=normalize_person_name(last_name, "last_name"),
            cuit=normalize_cuit(cuit),
            country=SERVED_COUNTRY,
        )
