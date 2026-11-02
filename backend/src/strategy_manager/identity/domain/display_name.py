"""The name a user goes by in front of other users (multi-user decision 27).

The public list names a strategy's author, and an e-mail never reaches another
user. The unique index on ``lower()`` can only tell apart what is spelled apart, so
one name that looks the same must have one spelling here: compatibility forms and
whitespace fold, and a character nobody can see is refused. Letters that merely look
alike across alphabets are not caught.
"""

import unicodedata

MIN_LENGTH = 3
MAX_LENGTH = 30

#: What draws no ink although its Unicode category is a mark, a letter or a symbol:
#: Default_Ignorable_Code_Point outside the ``C*`` categories, plus the braille blank.
#: Read after NFKC, which folds U+3164 and U+FFA0 into U+1160.
_BLANK_RANGES = (
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x115F, 0x1160),  # Hangul fillers
    (0x17B4, 0x17B5),  # Khmer inherent vowels
    (0x180B, 0x180D),  # Mongolian variation selectors
    (0x180F, 0x180F),  # Mongolian variation selector four
    (0x2800, 0x2800),  # braille blank
    (0xFE00, 0xFE0F),  # variation selectors
    (0xE0100, 0xE01EF),  # variation selectors supplement
)


class InvalidDisplayNameError(ValueError):
    pass


def _is_invisible(character: str) -> bool:
    if unicodedata.category(character).startswith("C"):
        return True
    code_point = ord(character)
    return any(first <= code_point <= last for first, last in _BLANK_RANGES)


def normalize_display_name(raw: str) -> str:
    """The one spelling of a name, or ``InvalidDisplayNameError``.

    The last two rules are also why the name can sit next to a strategy: ``@`` keeps
    anyone from publishing their e-mail by accident, and an invisible character would
    let ``A<zero-width>na`` pass as ``Ana``."""

    name = " ".join(unicodedata.normalize("NFKC", raw).split())
    if not MIN_LENGTH <= len(name) <= MAX_LENGTH:
        raise InvalidDisplayNameError(
            f"a name has {MIN_LENGTH} to {MAX_LENGTH} characters"
        )
    if "@" in name:
        raise InvalidDisplayNameError("a name holds no @")
    if any(_is_invisible(character) for character in name):
        raise InvalidDisplayNameError("a name holds no invisible characters")
    return name
