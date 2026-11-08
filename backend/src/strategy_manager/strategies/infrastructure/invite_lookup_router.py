"""``POST /public/invite-codes/lookup``: which strategy an invitation code opens
(multi-user decision 41; tasks.md K.6).

Explore's "I have a code" knows no strategy: the reader types the code alone, and
the panel opens the page of the strategy it names, where the code is read again
with that strategy's id. A code's hash is unique across every strategy
(``ux_invite_codes_code_hash``), so a code names at most one.

**Looking spends nothing.** The code is spent only by subscribing, as on the page.

**It counts like every other code.** A wrong, malformed or dead code is a failure of
the reader's, against the same limit the page and subscribing use, so a code cannot
be guessed here faster than there. A dead code says why (410), naming nobody and no
strategy; a wrong one is a 404; the limit is a 429.

**The code travels in the body**, not the path, so no access log keeps it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.strategies.domain.invite_code import (
    InviteCodeNotLive,
    TooManyCodeAttempts,
)
from strategy_manager.strategies.infrastructure.code_entry_http import (
    CODE_MAX_LENGTH,
    CodeCheckDep,
    code_refusal,
)

router = APIRouter(prefix="/public/invite-codes", tags=["public"])


class LookupRequest(BaseModel):
    code: Annotated[str, Field(max_length=CODE_MAX_LENGTH)]


class LookupBody(BaseModel):
    strategy_id: UUID


@router.post("/lookup", response_model=LookupBody)
async def look_up_invite_code(
    request: LookupRequest,
    codes: CodeCheckDep,
    user: Annotated[User, Depends(current_user)],
) -> LookupBody:
    try:
        strategy_id = await codes.locate(user.id, request.code)
    except (TooManyCodeAttempts, InviteCodeNotLive) as exc:
        raise code_refusal(exc) from exc
    if strategy_id is None:
        raise HTTPException(status_code=404, detail="no strategy opens to that code")
    return LookupBody(strategy_id=strategy_id)
