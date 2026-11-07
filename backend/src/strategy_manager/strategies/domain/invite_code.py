"""An invitation code to a strategy off the public list (multi-user decision 41).

**The code.** Eight characters of Crockford's base32, shown as ``XXXX-XXXX``: 40
bits, drawn by ``secrets.randbelow`` unless a test hands its own. Crockford's
alphabet leaves out ``I``, ``L``, ``O`` and ``U``, and reads the first three as the
digit they resemble, so a code read aloud or copied by hand still works. Typed
back, case, dashes and spaces are ignored; anything else is no code.

**What is kept.** Only the SHA-256 hex of the eight characters, and a hint of the
last four for the author's list: the code itself is shown once. 40 bits hashed
without a key could be searched offline by someone holding the database; the codes
live 7 days, are single use, and that reader already holds far more than a seat,
so the decision keeps the plain hash. Guessing online is the API's to stop: it
counts failed attempts per user (tasks.md K.4).

**A code is live** from its making until it expires, is revoked or is redeemed,
whichever comes first. Nothing here reads a clock: the caller hands ``now``.
"""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CODE_LIFETIME = timedelta(days=7)
CODE_LENGTH = 8
HINT_LENGTH = 4
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOOK_ALIKES = str.maketrans({"I": "1", "L": "1", "O": "0"})
_IGNORED = str.maketrans("", "", "- ")


@dataclass(frozen=True, slots=True)
class InviteCode:
    """One code, in its canonical eight characters. ``repr`` names none of them."""

    value: str = field(repr=False)

    @classmethod
    def generate(cls, randbelow: Callable[[int], int] = secrets.randbelow) -> "InviteCode":
        return cls("".join(ALPHABET[randbelow(len(ALPHABET))] for _ in range(CODE_LENGTH)))

    @classmethod
    def parse(cls, text: str) -> "InviteCode | None":
        """The code a user typed, or None when it cannot be one."""
        canonical = text.upper().translate(_IGNORED).translate(_LOOK_ALIKES)
        if len(canonical) != CODE_LENGTH or any(char not in ALPHABET for char in canonical):
            return None
        return cls(canonical)

    @property
    def display(self) -> str:
        """How the code is shown once to its author: ``XXXX-XXXX``."""
        return f"{self.value[:HINT_LENGTH]}-{self.value[HINT_LENGTH:]}"

    @property
    def hash(self) -> str:
        """The SHA-256 hex of the eight characters: the value stored and looked up."""
        return hashlib.sha256(self.value.encode("ascii")).hexdigest()

    @property
    def hint(self) -> str:
        """The last four characters, kept beside the hash for the author's list."""
        return self.value[-HINT_LENGTH:]


@dataclass(frozen=True, slots=True)
class IssuedCode:
    """What decides whether a stored code still opens anything."""

    expires_at: datetime
    revoked_at: datetime | None = None
    redeemed_at: datetime | None = None

    @classmethod
    def new(cls, created_at: datetime) -> "IssuedCode":
        return cls(expires_at=created_at + CODE_LIFETIME)

    def is_live(self, now: datetime) -> bool:
        return self.revoked_at is None and self.redeemed_at is None and now < self.expires_at
