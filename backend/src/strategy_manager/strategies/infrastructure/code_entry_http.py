"""What every route that takes a link or a code shares (multi-user decision 41;
tasks.md K.4): the inputs, the code check on a session of its own, and the two
refusals a code earns.

**The check runs on a connection of its own**, so it commits the failures it writes
even when the request then answers a refusal and rolls its own session back.

That connection is never drawn from the request's pool. The request holds a pooled
connection of its own while its code is checked (its snapshot, or its strategy read),
so with both drawn from one pool, as many concurrent checks as connections held every
one and waited for a second until the pool timed out: a 500 for each, and a stall for
every request beside them, the webhook's included. The check's engine has no pool
(``NullPool``): it opens a connection, and closes it when the check commits. A check
runs only inside a request that already holds a pooled connection, so the pool's size
bounds how many are open at once. The engine is the request session's own database's,
so whatever the request reads, the check reads too.

**Refusals.** A dead code is a 410 with its reason, ``EXPIRED``, ``REVOKED`` or
``SPENT``, which names nobody. The limit is a 429. A wrong code is not refused here:
each route answers it with the 404 of a strategy that does not exist.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.pool import NullPool

from strategy_manager.shared.db import create_engine_for, get_session
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.code_entry import CheckInviteCode
from strategy_manager.strategies.domain.invite_code import (
    InviteCodeNotLive,
    TooManyCodeAttempts,
)
from strategy_manager.strategies.infrastructure.code_attempts_adapter import (
    SqlAlchemyCodeAttempts,
)

#: Longer than any token or code, shorter than anything worth reading.
LINK_MAX_LENGTH = 64
CODE_MAX_LENGTH = 32

LinkQuery = Annotated[str | None, Query(max_length=LINK_MAX_LENGTH)]
CodeQuery = Annotated[str | None, Query(max_length=CODE_MAX_LENGTH)]


#: One engine per database, built once: it holds no connection, only the dialect.
_CHECK_ENGINES: dict[str, AsyncEngine] = {}


def _check_engine(session: AsyncSession) -> AsyncEngine:
    bind = session.bind
    if bind is None:
        raise InvariantViolation("the request's session is bound to no database")
    engine = bind.engine if isinstance(bind, AsyncConnection) else bind
    # The key holds the password; it is a dictionary key and is never logged.
    url = engine.url.render_as_string(hide_password=False)
    check_engine = _CHECK_ENGINES.get(url)
    if check_engine is None:
        check_engine = create_engine_for(url, poolclass=NullPool)
        _CHECK_ENGINES[url] = check_engine
    return check_engine


async def get_code_check(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[CheckInviteCode]:
    async with AsyncSession(_check_engine(session), expire_on_commit=False) as own:
        yield CheckInviteCode(SqlAlchemyCodeAttempts(own), SystemClock())


CodeCheckDep = Annotated[CheckInviteCode, Depends(get_code_check)]


def code_refusal(exc: TooManyCodeAttempts | InviteCodeNotLive) -> HTTPException:
    if isinstance(exc, TooManyCodeAttempts):
        return HTTPException(
            status_code=429, detail={"error": "TOO_MANY_CODE_ATTEMPTS", "message": str(exc)}
        )
    return HTTPException(
        status_code=410,
        detail={
            "error": "INVITE_CODE_NOT_LIVE",
            "reason": exc.reason.value,
            "message": str(exc),
        },
    )
