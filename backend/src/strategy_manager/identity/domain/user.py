"""A user of the system: the e-mail Cloudflare Access verified (multi-user
decision 1). No password and no login of the app's own exist anywhere."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InvalidEmailError(ValueError):
    pass


def normalize_email(raw: str) -> str:
    """The one spelling of an address: trimmed and lower-cased.

    Access reports what the identity provider sent, and a provider may keep the
    case the person typed, so ``Owner@x`` and ``owner@x`` must be one user. The
    check is deliberately shallow -- one ``@`` with something on each side and
    no inner whitespace. Access already verified the address; this only refuses
    a value that cannot be one, so a broken claim never becomes a user."""

    email = raw.strip().lower()
    local, at, domain = email.partition("@")
    if not at or not local or not domain or "@" in domain or any(c.isspace() for c in email):
        raise InvalidEmailError("not an e-mail address")
    return email


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    created_at: datetime
    last_seen_at: datetime
