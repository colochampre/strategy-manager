"""A strategy's link token (multi-user decision 41).

Whoever holds the link of a LINK strategy may read its page and subscribe. The token
is made when the strategy turns LINK and dropped when it leaves, so a link that has
leaked dies with one change of visibility. It is stored readable, unlike the webhook
secret, so the author's aside can always show it: the decision weighed that and
chose it, since whoever reads the database holds far more than a page.

The shape is what ``secrets.token_urlsafe(32)`` writes, 43 URL-safe characters, and
``ck_strategies_share_token_shape`` (migration 0038) checks the same.
"""

import re
import secrets

_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}")


def new_share_token() -> str:
    """32 random bytes, URL-safe, so the token rides in a link as it is."""
    return secrets.token_urlsafe(32)


def is_share_token(text: str) -> bool:
    """Whether ``text`` could be a token at all, so a malformed one is answered
    before any lookup."""
    return _SHAPE.fullmatch(text) is not None


def link_opens(token: str | None, link: str | None) -> bool:
    """Whether ``link`` is the strategy's current token. A strategy that is not LINK
    holds none, so no link opens it. Compared in constant time."""
    if token is None or link is None:
        return False
    return secrets.compare_digest(token.encode(), link.encode())
