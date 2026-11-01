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


class InvalidDisplayNameError(ValueError):
    pass


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
    if any(unicodedata.category(character).startswith("C") for character in name):
        raise InvalidDisplayNameError("a name holds no invisible characters")
    return name
