"""``GET /pools/{exchange}/{venue}/{settlement_currency}/available-pairs``: the
pairs a pool's venue lists, for the strategy dialog's selector (decision 41,
design addendum § F).

Read-only: it places nothing, writes nothing and needs no credential. The venue
is read through a public, unsigned transport, and ``DRY_RUN`` is deliberately
not consulted: the list is public data, and the validation it feeds has to be
true before the system goes live, not after.

**The three path values never steer an outbound request.** They select a
``capital_pools`` row and a registry entry; the base URLs come from ``Settings``
and the venue path is fixed. A pool that is not a row is answered 404 BEFORE the
catalogue is asked, so a made-up path causes neither a venue call nor a cache
entry.

* the pool is not a ``capital_pools`` row: 404 ``{"detail": "no such pool"}``;
* the pool exists but is disabled: 200 and the list (the catalogue needs no key);
* the pool exists and has no catalogue source (Pionex): 404
  ``PAIR_CATALOGUE_NOT_SERVED``, never an empty list;
* the venue cannot be read: 502 ``PAIR_CATALOGUE_UNAVAILABLE``.

The whole sorted list is returned (about 800 strings for Bybit, 10 to 15 KB):
search is client-side, and the selector needs all of it to mark a stored pair as
no longer listed. It carries no money, quantity or ratio.

Authentication is attached to the ROUTER, as on every ``/api`` router, so it
holds for any route added below without its author doing anything.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.strategies.application.ports import PairCatalogPort
from strategy_manager.strategies.application.read_available_pairs import (
    ReadAvailablePairs,
    UnknownPool,
)
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)
from strategy_manager.strategies.infrastructure.pool_catalog import SqlAlchemyPoolCatalog

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pools",
    tags=["pools"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

NOT_SERVED = "PAIR_CATALOGUE_NOT_SERVED"
UNAVAILABLE = "PAIR_CATALOGUE_UNAVAILABLE"


def get_pair_catalog(request: Request) -> PairCatalogPort:
    """The ONE ``VenuePairCatalog`` ``create_app()`` keeps on ``app.state``, so
    the cache is shared by every request and every route that asks. Tests
    override this dependency with a fake, so no router test needs a network."""
    catalog: PairCatalogPort = request.app.state.pair_catalog
    return catalog


def get_read_available_pairs(
    session: SessionDep, pairs: Annotated[PairCatalogPort, Depends(get_pair_catalog)]
) -> ReadAvailablePairs:
    return ReadAvailablePairs(SqlAlchemyPoolCatalog(session), pairs)


class PoolRef(BaseModel):
    exchange: str
    venue: str
    settlement_currency: str


class AvailablePairsBody(BaseModel):
    pool: PoolRef
    pairs: list[str]
    count: int


@router.get(
    "/{exchange}/{venue}/{settlement_currency}/available-pairs",
    response_model=AvailablePairsBody,
)
async def available_pairs(
    exchange: str,
    venue: str,
    settlement_currency: str,
    use_case: Annotated[ReadAvailablePairs, Depends(get_read_available_pairs)],
) -> AvailablePairsBody:
    try:
        pairs = await use_case.execute((exchange, venue, settlement_currency))
    except UnknownPool:
        # The values are the caller's own text: ``%r`` keeps a newline out of the
        # log line and the precision keeps one line short.
        logger.warning(
            "available pairs refused, no such pool: %.80r/%.80r/%.80r",
            exchange,
            venue,
            settlement_currency,
        )
        raise HTTPException(status_code=404, detail="no such pool") from None
    except PairCatalogNotServed:
        logger.warning(
            "available pairs refused, catalogue not served for pool %s/%s/%s",
            exchange,
            venue,
            settlement_currency,
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error": NOT_SERVED,
                "message": "pairs cannot be listed for this pool: no catalogue is served for it",
            },
        ) from None
    except PairCatalogUnavailable:
        # The adapter already logged the venue failure (pool, error class, code).
        raise HTTPException(
            status_code=502,
            detail={
                "error": UNAVAILABLE,
                "message": "the exchange's pair list could not be read; try again",
            },
        ) from None
    return AvailablePairsBody(
        pool=PoolRef(exchange=exchange, venue=venue, settlement_currency=settlement_currency),
        pairs=pairs,
        count=len(pairs),
    )
