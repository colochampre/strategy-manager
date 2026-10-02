"""Reads the whole ``linear`` instrument listing, page by page.

One loop for both ways of reading the catalogue: the unsigned one the API
process uses (``public_catalogue``) and the signed one the order path uses
(``BybitReadOnlyClient.perp_contracts``). Two loops would be two chances to
disagree about when a listing ends, and a listing that ends early turns valid
pairs into "not listed".

**It cannot silently truncate.** The cursor is followed until Bybit returns an
empty one. Bybit ends its last page with an EMPTY ``nextPageCursor`` rather
than an absent field (probe P7, 2026-10-02), and an absent field ends the read
too. A page cap raises rather than returning a partial list.

This module only transports pages. It parses nothing: what an entry means, and
whether a malformed one is skipped or refused, stays with the caller.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError

INSTRUMENTS_PATH: Final = "/v5/market/instruments-info"
LINEAR: Final = "linear"

PAGE_LIMIT: Final = 1000

# Probe P7 (2026-10-02): 891 linear entries, so one page of 1000 today. Ten
# pages is ten times the current listing; reaching it means something is wrong,
# and a partial list must never be returned for it.
MAX_PAGES: Final = 10

PageGetter = Callable[[str, Mapping[str, str]], Awaitable[Any]]


async def read_every_page(
    get: PageGetter,
    *,
    page_limit: int = PAGE_LIMIT,
    reject_repeated_cursor: bool = False,
) -> tuple[list[Any], int]:
    """Every raw entry of the ``linear`` listing, and how many pages it took.

    ``get`` performs one request (signed or not, the caller decides) and
    returns the envelope's ``result``.

    ``reject_repeated_cursor`` raises as soon as Bybit hands back a cursor it
    already gave, instead of requesting the same page until the cap. The order
    path turns it on so a stuck cursor fails at once and names itself.
    """
    entries: list[Any] = []
    seen: set[str] = set()
    cursor = ""
    for page in range(1, MAX_PAGES + 1):
        params = {"category": LINEAR, "limit": str(page_limit)}
        if cursor:
            params["cursor"] = cursor
        data = await get(INSTRUMENTS_PATH, params)
        if not isinstance(data, dict):
            raise BybitApiError(
                f"GET {INSTRUMENTS_PATH} returned no result object, got "
                f"{type(data).__name__}"
            )
        listed = data.get("list")
        if not isinstance(listed, list):
            raise BybitApiError(
                f"expected 'list' to be a list, got {type(listed).__name__}; "
                f"payload keys were {sorted(data)}"
            )
        entries.extend(listed)
        cursor = str(data.get("nextPageCursor") or "")
        if not cursor:
            return entries, page
        if reject_repeated_cursor:
            if cursor in seen:
                raise BybitApiError(
                    f"the {LINEAR} catalogue repeated a page cursor after "
                    f"{page} pages; returning the {len(entries)} entries read so "
                    "far would drop valid pairs"
                )
            seen.add(cursor)

    raise BybitApiError(
        f"the {LINEAR} catalogue did not end within {MAX_PAGES} pages of "
        f"{page_limit}; returning the {len(entries)} entries read so far would "
        "drop valid pairs"
    )
