"""The owner's ``users`` row, for the tests that write owned rows (multi-user
design AD2; tasks.md B.9).

Migration ``0030`` gives every owned row an owner: ``strategies.author_id`` and
the ``user_id`` of every other owned table reference ``users(id)`` and are
``NOT NULL``. A test that inserts one of those rows therefore needs a user row
first, and the owner is the user a single-user test means.

``OWNER_ID`` is fixed, so a seed helper can default to it without the test
threading an id through. ``OWNER_EMAIL`` is deliberately NOT the admin's e-mail
of ``tests.identity_auth``: a router test that signs in as the admin resolves its
own ``User``, with a fresh id, and a strategy that ended up carrying ``OWNER_ID``
instead of that id would then be told apart.

``users`` is never named by the integration fixtures' ``TRUNCATE ... CASCADE``
(it references nothing, so nothing cascades into it), so the owner's row
outlives one fixture. ``seed_owner`` is therefore idempotent and every fixture
calls it after its truncate: a test that truncated ``users`` itself (the
identity tests do) leaves no gap behind.
"""

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

OWNER_ID = UUID("0a1b2c3d-0000-4000-8000-00000000a0a0")
OWNER_EMAIL = "fixture-owner@example.com"


async def seed_user(
    executor: AsyncConnection | AsyncSession, email: str, user_id: UUID | None = None
) -> UUID:
    """Insert one ``users`` row and return its id. Not committed: the caller's
    transaction owns it. A duplicate id or e-mail raises, as it should."""
    user_id = user_id or uuid4()
    await executor.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": email},
    )
    return user_id


async def seed_owner(executor: AsyncConnection | AsyncSession) -> UUID:
    """The owner's row, inserted unless it is already there. Not committed."""
    await executor.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email) ON CONFLICT DO NOTHING"),
        {"id": OWNER_ID, "email": OWNER_EMAIL},
    )
    return OWNER_ID
