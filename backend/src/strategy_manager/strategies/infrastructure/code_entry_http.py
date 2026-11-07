"""What every route that takes a link or a code shares (multi-user decision 41;
tasks.md K.4): the inputs, the code check on a session of its own, and the two
refusals a code earns.

``Depends(get_session, use_cache=False)`` opens a second session for the request:
the check commits the failures it writes even when the request then answers a
refusal and rolls its own session back.

**Refusals.** A dead code is a 410 with its reason, ``EXPIRED``, ``REVOKED`` or
``SPENT``, which names nobody. The limit is a 429. A wrong code is not refused here:
each route answers it with the 404 of a strategy that does not exist.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.db import get_session
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


def get_code_check(
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
) -> CheckInviteCode:
    return CheckInviteCode(SqlAlchemyCodeAttempts(session), SystemClock())


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
