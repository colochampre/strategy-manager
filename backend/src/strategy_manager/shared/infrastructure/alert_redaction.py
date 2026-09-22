"""Scrubs a log-derived string before it leaves the process inside an alert.

The log is not a curated surface. httpx logs the signed venue URL at INFO, a
SQLAlchemy traceback has already printed a database DSN once, and a repr of a
credentials object prints both halves of a key pair. None of that is a problem
while it stays in a journal on a host we control; all of it is a problem the
moment it is forwarded to a third-party chat service and mirrored onto a phone.

So the boundary is scrubbed, not every site that could ever log something. A
defence applied at the one place everything passes through is a defence whose
failure is visible; one applied at N call sites is a defence that silently
stops holding the first time an N+1th is added.

Every rule keeps the NAME and removes the VALUE, the same choice
``access_log.py`` makes for the webhook secret: a redacted line still has to
show that a secret was present, or a call carrying credentials reads exactly
like one that carried none.
"""

import re

# A Telegram bot token, which rides in the URL PATH rather than the query —
# so stripping the query below would not reach it. Redacted FIRST, because
# this is the one secret the alerting channel itself holds: an httpx error
# naming the failing request URL would otherwise carry the token into the very
# channel it authenticates.
_BOT_TOKEN_IN_PATH = re.compile(r"(?i)\bbot\d{6,}:[A-Za-z0-9_-]{25,}")
_BARE_BOT_TOKEN = re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{25,}\b")

# scheme://user:pass@host — a database DSN, an AMQP URL, an HTTP proxy with
# inline credentials. The host and database are kept: which server refused the
# connection is the whole diagnostic value of the message.
_DSN_CREDENTIALS = re.compile(r"\b([A-Za-z][A-Za-z0-9+.\-]*)://[^\s/:@]+:[^\s/@]+@")

# Any URL's query string. The signature, the api_key and the timestamp all
# travel there on both venues, and a signed URL is logged on every single call.
_URL_QUERY = re.compile(r"\b([A-Za-z][A-Za-z0-9+.\-]*://[^\s?#]+)\?[^\s#]*")

# name=value / "name": "value" — a kwargs dump, a JSON body, a dataclass repr.
_NAMED_SECRET = re.compile(
    r"""(?ix)
    ( \b (?: api[-_\ ]?secret
           | api[-_\ ]?key
           | secret[-_\ ]?key
           | secret
           | token
           | password | passwd | pwd
           | private[-_\ ]?key
           | signature | sign
        ) \b ["']? \s* [:=] \s* )
    (["']?)
    ( [^\s,;"'&}\)\]]+ )
    \2
    """
)

_BEARER = re.compile(r"(?i)\bbearer\s+\S+")

_PLACEHOLDER = "REDACTED"


def redact(text: str) -> str:
    """Returns ``text`` with every known secret shape replaced in place.

    Deliberately conservative about what it rewrites: an alert whose body has
    been mangled costs the alert its meaning, and a mangled alert is
    indistinguishable from a mangled system. Ordinary prose passes through
    untouched.
    """

    text = _BOT_TOKEN_IN_PATH.sub(f"bot<{_PLACEHOLDER}>", text)
    text = _BARE_BOT_TOKEN.sub(f"<{_PLACEHOLDER}>", text)
    text = _DSN_CREDENTIALS.sub(rf"\1://{_PLACEHOLDER}@", text)
    text = _URL_QUERY.sub(rf"\1?{_PLACEHOLDER}", text)
    text = _NAMED_SECRET.sub(rf"\1\2{_PLACEHOLDER}\2", text)
    return _BEARER.sub(f"Bearer {_PLACEHOLDER}", text)
