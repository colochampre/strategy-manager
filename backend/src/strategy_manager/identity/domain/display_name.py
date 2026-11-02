"""The name a user goes by in front of other users (multi-user decision 27).

The public list names a strategy's author, and an e-mail never reaches another
user. The unique index on ``lower()`` can only tell apart what is spelled apart, so
one name that looks the same must have one spelling here: compatibility forms and
whitespace fold, a character nobody can see is refused, and so is a name that mixes
alphabets whose letters look alike (decision 32). A name written wholly in one of
them can still imitate another: ``Асе`` in Cyrillic reads as ``Ace``.
"""

import unicodedata

MIN_LENGTH = 3
MAX_LENGTH = 30

#: What draws no ink although its Unicode category is a mark, a letter or a symbol:
#: Default_Ignorable_Code_Point outside the ``C*`` categories, the braille blank, and
#: two that Unicode draws but a browser may not. U+133FC draws nothing in Edge on
#: Windows through the panel's fonts (seen 2026-11-01), so it reads as a space or as
#: no character at all. Read after NFKC, which folds U+3164 and U+FFA0 into U+1160.
_BLANK_RANGES = (
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x115F, 0x1160),  # Hangul fillers
    (0x17B4, 0x17B5),  # Khmer inherent vowels
    (0x180B, 0x180D),  # Mongolian variation selectors
    (0x180F, 0x180F),  # Mongolian variation selector four
    (0x2800, 0x2800),  # braille blank
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFFFC, 0xFFFC),  # object replacement character
    (0x133FC, 0x133FC),  # Egyptian hieroglyph Z015B
    (0xE0100, 0xE01EF),  # variation selectors supplement
)


#: The alphabets with letters that pass for Latin ones, or for each other, as the
#: first word of a Unicode character name. Python's ``unicodedata`` has no script
#: property. Other scripts stay out: no letter of theirs reads as one of these.
_LOOK_ALIKE_ALPHABETS = frozenset({"LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE"})


class InvalidDisplayNameError(ValueError):
    pass


def _alphabet(character: str) -> str | None:
    """Letters only: U+271D is called ``LATIN CROSS`` and is a symbol."""
    if not unicodedata.category(character).startswith("L"):
        return None
    first_word = unicodedata.name(character, "").split(" ", 1)[0]
    return first_word if first_word in _LOOK_ALIKE_ALPHABETS else None


def _mixes_alphabets(name: str) -> bool:
    return len({_alphabet(character) for character in name} - {None}) > 1


def _is_invisible(character: str) -> bool:
    if unicodedata.category(character).startswith("C"):
        return True
    code_point = ord(character)
    return any(first <= code_point <= last for first, last in _BLANK_RANGES)


def normalize_display_name(raw: str) -> str:
    """The one spelling of a name, or ``InvalidDisplayNameError``.

    The last three rules are also why the name can sit next to a strategy: ``@`` keeps
    anyone from publishing their e-mail by accident, an invisible character would let
    ``A<zero-width>na`` pass as ``Ana``, and so would a Cyrillic ``А``."""

    name = " ".join(unicodedata.normalize("NFKC", raw).split())
    if not MIN_LENGTH <= len(name) <= MAX_LENGTH:
        raise InvalidDisplayNameError(
            f"a name has {MIN_LENGTH} to {MAX_LENGTH} characters"
        )
    if "@" in name:
        raise InvalidDisplayNameError("a name holds no @")
    if any(_is_invisible(character) for character in name):
        raise InvalidDisplayNameError("a name holds no invisible characters")
    if _mixes_alphabets(name):
        raise InvalidDisplayNameError("a name keeps to one alphabet")
    return name
