"""``GET /admin/users``: every user with their state, for the admin (tasks.md F.7,
decision 8).

**A body is an explicit list.** ``AdminUserBody`` is built field by field, and it
holds no amount and no performance: the admin can support a user and understand a
discrepancy without seeing anyone's portfolio. ``test_users_router.py`` pins its
keys.

**"With no key" is what the database can say.** An exchange there has an enabled
pool and no active key. The worker's own degraded tracking lives in its process.

**Last seen** is ``last_seen_at``, at most a minute stale.

The route reads in one read-only ``REPEATABLE READ`` snapshot, in a fixed number
of statements however many users there are.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from strategy_manager.admin.application.read_users import ReadUsers, UserState
from strategy_manager.admin.infrastructure.users_source import SqlAlchemyUsersSource
from strategy_manager.identity.infrastructure.dependencies import require_admin
from strategy_manager.performance.infrastructure.open_positions_router import (
    SnapshotSessionDep,
)
from strategy_manager.shared.infrastructure.wire import Instant

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class AdminUserBody(BaseModel):
    email: str
    display_name: str | None
    mode: str
    exchanges_with_key: list[str]
    exchanges_with_no_key: list[str]
    subscriptions: int
    open_positions: int
    last_seen_at: Instant


def _body(state: UserState) -> AdminUserBody:
    return AdminUserBody(
        email=state.email,
        display_name=state.display_name,
        mode=state.mode.value,
        exchanges_with_key=list(state.exchanges_with_key),
        exchanges_with_no_key=list(state.exchanges_with_no_key),
        subscriptions=state.subscriptions,
        open_positions=state.open_positions,
        last_seen_at=state.last_seen_at,
    )


@router.get("", response_model=list[AdminUserBody])
async def list_users(session: SnapshotSessionDep) -> list[AdminUserBody]:
    states = await ReadUsers(SqlAlchemyUsersSource(session)).read()
    return [_body(state) for state in states]
