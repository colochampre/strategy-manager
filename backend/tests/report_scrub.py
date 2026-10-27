"""Removes credentials from the text of a failed test's report.

pytest reports a failing assertion with the arguments of the calls inside it,
and most database tests hand a throwaway URL, password included, to their
helpers. ``tests/conftest.py`` passes every failed report through
``scrub_credentials`` before it is printed (seen 2026-10-27).
"""

import re
from collections.abc import Iterable

# A URL that carries ``user[:password]@``: the userinfo is what must not leak,
# and the rest of such a URL is not worth keeping beside it.
_URL_WITH_CREDENTIALS = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>/@]+@[^\s'\"<>]*")


def scrub_credentials(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every URL that carries credentials replaced by
    ``<database url>``, then every non-empty secret by ``<redacted>``."""
    clean = _URL_WITH_CREDENTIALS.sub("<database url>", text)
    for secret in secrets:
        if secret:
            clean = clean.replace(secret, "<redacted>")
    return clean
