"""What every route that takes a link or a code shares (multi-user decision 41;
tasks.md K.4): the inputs, the code check on a session of its own, and the two
refusals a code earns.

**The check runs on a connection of its own**, so it commits the failures it writes
even when the request then answers a refusal and rolls its own session back.

That connection is never drawn from the request's pool. The request may hold a pooled
connection of its own while its code is checked (its snapshot, or its strategy read),
so with both drawn from one pool, as many concurrent checks as connections held every
one and waited for a second until the pool timed out: a 500 for each, and a stall for
every request beside them, the webhook's included.

**The checks have a pool of their own**, ``CHECK_POOL_SIZE`` connections with no
overflow. A check holding one never waits for the request's pool, so the two cannot
wait on each other. And it is bounded: a lookup holds no connection of its request, and
a check waits on its user's lock holding its connection, so with no pool at all one
user's concurrent lookups opened a connection each, enough to use up the server's.
A check that waits ``CHECK_POOL_TIMEOUT_SECONDS`` for a slot fails, and nothing else
does.

The pool is built for the request session's own engine, so whatever the request reads,
the check reads too, and it is closed when that engine is disposed.

**Refusals.** A dead code is a 410 with its reason, ``EXPIRED``, ``REVOKED`` or
``SPENT``, which names nobody. The limit is a 429. A wrong code is not refused here:
each route answers it with the 404 of a strategy that does not exist.
"""

from collections.abc import AsyncIterator, Callable
from typing import Annotated
from weakref import WeakKeyDictionary

from fastapi import Depends, HTTPException, Query
from sqlalchemy import Engine, event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from strategy_manager.shared.db import PoolBounds, create_engine_for, get_session
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

#: How many code checks run at once in this process, each on a connection of its own.
CHECK_POOL_SIZE = 3
CHECK_POOL_TIMEOUT_SECONDS = 10.0

LinkQuery = Annotated[str | None, Query(max_length=LINK_MAX_LENGTH)]
CodeQuery = Annotated[str | None, Query(max_length=CODE_MAX_LENGTH)]


#: The checks' engine of each request engine, alive as long as it is.
_CHECK_ENGINES: "WeakKeyDictionary[Engine, AsyncEngine]" = WeakKeyDictionary()


def check_engine_for(session: AsyncSession) -> AsyncEngine:
    bind = session.bind
    if bind is None:
        raise InvariantViolation("the request's session is bound to no database")
    request_engine = (bind.engine if isinstance(bind, AsyncConnection) else bind).sync_engine
    check_engine = _CHECK_ENGINES.get(request_engine)
    if check_engine is None:
        check_engine = create_engine_for(
            request_engine.url.render_as_string(hide_password=False),
            bounds=PoolBounds(size=CHECK_POOL_SIZE, timeout_seconds=CHECK_POOL_TIMEOUT_SECONDS),
        )
        _CHECK_ENGINES[request_engine] = check_engine
        event.listen(request_engine, "engine_disposed", _closing(check_engine))
    return check_engine


def _closing(check_engine: AsyncEngine) -> Callable[[Engine], None]:
    """Closes the checks' pool with the request engine's. ``AsyncEngine.dispose`` runs
    the sync dispose inside a greenlet, so the checks' sync dispose may close its
    connections there."""

    def close(_request_engine: Engine) -> None:
        check_engine.sync_engine.dispose()

    return close


async def get_code_check(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[CheckInviteCode]:
    async with AsyncSession(check_engine_for(session), expire_on_commit=False) as own:
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
