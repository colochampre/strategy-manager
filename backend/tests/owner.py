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

from datetime import datetime
from decimal import Decimal
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


async def seed_other_user(executor: AsyncConnection | AsyncSession) -> UUID:
    """A second user, with a fresh id and e-mail, for the cross-user tests
    (multi-user design AD8). Not committed. ``users`` outlives the fixtures'
    truncates, so the e-mail is unique per call."""
    user_id = uuid4()
    return await seed_user(executor, f"other-{user_id}@example.com", user_id)


async def seed_pool(
    executor: AsyncConnection | AsyncSession,
    market: tuple[str, str, str],
    *,
    user_id: UUID = OWNER_ID,
    enabled: bool = True,
    min_order_size: Decimal = Decimal("5"),
) -> int:
    """One ``capital_pools`` row of ``user_id`` on ``market``; returns its id.
    Not committed. A duplicate ``(user, market)`` raises, as it should."""
    exchange, venue, currency = market
    pool_id = (
        await executor.execute(
            text(
                "INSERT INTO capital_pools "
                "(user_id, exchange, venue, settlement_currency, enabled, min_order_size) "
                "VALUES (:user_id, :exchange, :venue, :currency, :enabled, :minimum) "
                "RETURNING id"
            ),
            {
                "user_id": user_id,
                "exchange": exchange,
                "venue": venue,
                "currency": currency,
                "enabled": enabled,
                "minimum": min_order_size,
            },
        )
    ).scalar_one()
    return int(pool_id)


async def ensure_pool(
    executor: AsyncConnection | AsyncSession,
    market: tuple[str, str, str],
    *,
    user_id: UUID = OWNER_ID,
) -> int:
    """The id of ``user_id``'s pool on ``market``, seeded with ``seed_pool``'s
    defaults when that user holds none. The owner's row is seeded too when the
    pool is the owner's. Not committed."""
    exchange, venue, currency = market
    existing = (
        await executor.execute(
            text(
                "SELECT id FROM capital_pools WHERE user_id = :user_id "
                "AND exchange = :exchange AND venue = :venue AND settlement_currency = :currency"
            ),
            {"user_id": user_id, "exchange": exchange, "venue": venue, "currency": currency},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    if user_id == OWNER_ID:
        await seed_owner(executor)
    return await seed_pool(executor, market, user_id=user_id)


async def seed_reservation_row(
    executor: AsyncConnection | AsyncSession,
    *,
    reservation_id: UUID,
    strategy_id: UUID,
    signal_id: UUID,
    market: tuple[str, str, str] = ("bybit", "usdt-m", "USDT"),
    amount: Decimal = Decimal("200"),
    status: str = "SUBMITTED",
    expires_at: datetime,
    user_id: UUID = OWNER_ID,
) -> int:
    """One ``reservations`` row of ``user_id``, in that user's pool on
    ``market`` (seeded when missing, ``ensure_pool``), written raw. Returns the
    pool's id. Not committed: the caller's transaction owns it."""
    pool_id = await ensure_pool(executor, market, user_id=user_id)
    exchange, venue, currency = market
    await executor.execute(
        text(
            "INSERT INTO reservations "
            "(id, user_id, pool_id, strategy_id, signal_id, exchange, venue, "
            "settlement_currency, amount, status, expires_at) "
            "VALUES (:id, :user_id, :pool_id, :strategy_id, :signal_id, :exchange, :venue, "
            ":settlement_currency, :amount, :status, :expires_at)"
        ),
        {
            "id": reservation_id,
            "user_id": user_id,
            "pool_id": pool_id,
            "strategy_id": strategy_id,
            "signal_id": signal_id,
            "exchange": exchange,
            "venue": venue,
            "settlement_currency": currency,
            "amount": amount,
            "status": status,
            "expires_at": expires_at,
        },
    )
    return pool_id


async def seed_snapshot(
    executor: AsyncConnection | AsyncSession,
    market: tuple[str, str, str],
    *,
    total: Decimal,
    available: Decimal,
    observed_at: datetime,
    user_id: UUID = OWNER_ID,
) -> None:
    """The ``pool_balance_snapshots`` row of ``user_id``'s pool on ``market``,
    written raw (not through the repository under test). The pool must exist.
    Not committed."""
    exchange, venue, currency = market
    inserted = await executor.execute(
        text(
            "INSERT INTO pool_balance_snapshots "
            "(pool_id, user_id, exchange, venue, settlement_currency, total, available, "
            "observed_at) "
            "SELECT id, user_id, exchange, venue, settlement_currency, :total, :available, "
            ":observed_at FROM capital_pools WHERE user_id = :user_id "
            "AND exchange = :exchange AND venue = :venue AND settlement_currency = :currency"
        ),
        {
            "user_id": user_id,
            "exchange": exchange,
            "venue": venue,
            "currency": currency,
            "total": total,
            "available": available,
            "observed_at": observed_at,
        },
    )
    if inserted.rowcount != 1:  # type: ignore[attr-defined]
        raise AssertionError(f"user {user_id} has no pool on {market} to snapshot")
