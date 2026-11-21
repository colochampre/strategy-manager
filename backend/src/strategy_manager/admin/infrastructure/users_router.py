"""``GET /admin/users``: every user with their state, for the admin (tasks.md F.7,
decision 8).

**A body is an explicit list.** ``AdminUserBody`` is built field by field, and it
holds no amount and no performance: the admin can support a user and understand a
discrepancy without seeing anyone's portfolio. ``test_users_router.py`` pins its
keys.

**"With no key" is what the database can say.** An exchange there has an enabled
pool and no active key. The worker's own degraded tracking lives in its process.

**Last seen** is ``last_seen_at``, at most a minute stale.

**The identity** is what the sign-up form gave: first and last name, CUIT and
country, as the privacy policy says the admin sees them (public-site LS3). It is
``null`` until the user signs up. Neither the declarations nor the acceptance
record are part of it.

**A deleted account is not listed** (account-deletion S6): its row names nobody.
``GET /admin/users/deleted-count`` says how many there are, a route of its own so
the list's body stays the list it was.

The route reads in one read-only ``REPEATABLE READ`` snapshot, in a fixed number
of statements however many users there are.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.admin.application.read_users import ReadUsers, UserState
from strategy_manager.admin.infrastructure.users_source import SqlAlchemyUsersSource
from strategy_manager.identity.application.suspend_account import (
    SuspendAccount,
    SuspensionRefusal,
    SuspensionRefusedError,
)
from strategy_manager.identity.domain.profile import Profile
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.account_deletion import (
    SqlAlchemyAuthoredStrategies,
)
from strategy_manager.identity.infrastructure.dependencies import current_user, require_admin
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.performance.infrastructure.open_positions_router import (
    SnapshotSessionDep,
)
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.wire import Instant
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class AdminIdentityBody(BaseModel):
    first_name: str
    last_name: str
    cuit: str
    country: str


class AdminUserBody(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    mode: str
    exchanges_with_key: list[str]
    exchanges_with_no_key: list[str]
    subscriptions: int
    open_positions: int
    last_seen_at: Instant
    identity: AdminIdentityBody | None
    suspended_at: Instant | None


def _identity(profile: Profile | None) -> AdminIdentityBody | None:
    if profile is None:
        return None
    return AdminIdentityBody(
        first_name=profile.first_name,
        last_name=profile.last_name,
        cuit=profile.cuit,
        country=profile.country,
    )


def _body(state: UserState) -> AdminUserBody:
    return AdminUserBody(
        id=state.id,
        email=state.email,
        display_name=state.display_name,
        mode=state.mode.value,
        exchanges_with_key=list(state.exchanges_with_key),
        exchanges_with_no_key=list(state.exchanges_with_no_key),
        subscriptions=state.subscriptions,
        open_positions=state.open_positions,
        last_seen_at=state.last_seen_at,
        identity=_identity(state.identity),
        suspended_at=state.suspended_at,
    )


class DeletedCountBody(BaseModel):
    deleted_accounts: int


@router.get("", response_model=list[AdminUserBody])
async def list_users(session: SnapshotSessionDep) -> list[AdminUserBody]:
    states = await ReadUsers(SqlAlchemyUsersSource(session)).read()
    return [_body(state) for state in states]


@router.get("/deleted-count", response_model=DeletedCountBody)
async def deleted_count(session: SnapshotSessionDep) -> DeletedCountBody:
    return DeletedCountBody(
        deleted_accounts=await SqlAlchemyUserRepository(session).count_deleted()
    )


class SuspensionRequest(BaseModel):
    """Exactly ``{"suspended": true}`` or ``{"suspended": false}``: no reason is
    stored (PS.13 S2), so a reason sent along is refused rather than dropped."""

    model_config = ConfigDict(extra="forbid")

    suspended: StrictBool


@router.put("/{user_id}/suspension", status_code=204)
async def set_suspension(
    user_id: UUID,
    body: SuspensionRequest,
    admin: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Suspends the account or lifts its suspension (public-site LS9, PS.13 S1)."""
    use_case = SuspendAccount(
        SqlAlchemyUserRepository(session),
        SqlAlchemyAuthoredStrategies(session, user_id),
        PoolLockAdapter(session),
        session,
    )
    try:
        await use_case.execute(
            admin_id=admin.id, user_id=user_id, suspended=body.suspended, now=datetime.now(UTC)
        )
    except SuspensionRefusedError as refused:
        # Nothing was written, but the pool locks may still be held: end the transaction.
        await session.rollback()
        status = 404 if refused.refusal is SuspensionRefusal.USER_NOT_FOUND else 409
        raise HTTPException(status_code=status, detail={"error": refused.refusal.value}) from None
