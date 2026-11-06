"""A strategy's description: plain text its author writes for anyone reading the
strategy, optional, carrying the recommended configuration (decision 38). There
is no separate field for a recommended leverage; each user chooses their own.

It is trimmed of spaces, tabs and line breaks, the same four characters the
``ck_strategies_description_shape`` CHECK of migration ``0037`` trims, so what
this module accepts the database accepts. A blank one is no description. Lines
and tabs inside it are kept; any other control character is refused, NUL among
them, which PostgreSQL would refuse anyway with an error nobody could read.
The length is counted in characters once trimmed, as ``char_length`` counts.
"""

from strategy_manager.shared.domain.errors import InvariantViolation

MAX_DESCRIPTION_LENGTH = 2000

_TRIMMED = " \t\r\n"
_KEPT_CONTROLS = frozenset("\t\r\n")


def description_of(text: str | None) -> str | None:
    """The description as it is stored, from what the author wrote. Raises
    ``InvariantViolation`` for one too long or holding a control character."""
    if text is None:
        return None
    trimmed = text.strip(_TRIMMED)
    if not trimmed:
        return None
    if len(trimmed) > MAX_DESCRIPTION_LENGTH:
        raise InvariantViolation(
            f"a description holds at most {MAX_DESCRIPTION_LENGTH} characters"
        )
    if any(_is_refused_control(character) for character in trimmed):
        raise InvariantViolation(
            "a description holds no control character other than a tab or a line break"
        )
    return trimmed


def _is_refused_control(character: str) -> bool:
    code = ord(character)
    return (code < 0x20 or code == 0x7F) and character not in _KEPT_CONTROLS
