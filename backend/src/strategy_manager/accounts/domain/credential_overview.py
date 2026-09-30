"""What the operator panel may know about one exchange's key (design 8a § C).

Pure data, no framework. It carries the last four characters of the key and the
facts recorded about it, and there is nowhere to put anything else: no secret,
no ciphertext, no raw permission payload. An exchange with no active key is
``EMPTY``, which is how the panel tells "nothing stored" from "stored".
"""

from dataclasses import dataclass
from datetime import datetime

from strategy_manager.accounts.domain.exchange_credential import KeyFacts


@dataclass(frozen=True, slots=True)
class StoredKey:
    """The active key of an exchange, as much of it as may be shown."""

    label: str
    last4: str
    stored_at: datetime
    facts: KeyFacts


@dataclass(frozen=True, slots=True)
class CredentialOverview:
    """One exchange. ``key`` is ``None`` when it has no active credential: it
    may still be listed because a superseded key exists, or because a pool on
    it is enabled (the DEGRADED case of decision 20)."""

    exchange: str
    key: StoredKey | None

    @property
    def status(self) -> str:
        return "EMPTY" if self.key is None else "STORED"
