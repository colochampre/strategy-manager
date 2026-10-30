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

import hashlib
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from strategy_manager.allocation.application.allocate_capital import AllocateCommand
from strategy_manager.shared.domain.money import Money

OWNER_ID = UUID("0a1b2c3d-0000-4000-8000-00000000a0a0")
OWNER_EMAIL = "fixture-owner@example.com"


def secret_hash(secret: str) -> str:
    """What ``strategies.webhook_secret_hash`` holds for ``secret`` (migration
    0033, multi-user design AD6): the SHA-256 hex of the secret's UTF-8 bytes."""
    return hashlib.sha256(secret.encode()).hexdigest()


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


async def ensure_author_subscription(
    executor: AsyncConnection | AsyncSession,
    strategy_id: UUID,
    *,
    share: Decimal | None = None,
    status: str = "ACTIVE",
) -> UUID:
    """The strategy's AUTHOR's subscription to it, seeded when the author holds no
    live one (``RegisterStrategy`` makes it in production). The pool is the
    author's own on the strategy's market, seeded when missing. The share is the
    100 unless given, the share a new subscription starts from. A test that
    drives a signal through the worker needs it: ``FanOutSignal`` delivers only
    to subscriptions, so a strategy seeded raw has nobody to work its signals.
    Not committed."""
    found = (
        await executor.execute(
            text(
                "SELECT s.id FROM subscriptions s JOIN strategies t ON t.id = s.strategy_id "
                "WHERE s.strategy_id = :strategy_id AND s.user_id = t.author_id "
                "AND s.status IN ('ACTIVE', 'LEAVING')"
            ),
            {"strategy_id": strategy_id},
        )
    ).scalar_one_or_none()
    if found is not None:
        return UUID(str(found))
    strategy = (
        await executor.execute(
            text(
                "SELECT author_id, exchange, venue, settlement_currency "
                "FROM strategies WHERE id = :strategy_id"
            ),
            {"strategy_id": strategy_id},
        )
    ).one()
    author_id = UUID(str(strategy[0]))
    if share is None:
        share = Decimal("100")
    pool_id = await ensure_pool(
        executor, (strategy[1], strategy[2], strategy[3]), user_id=author_id
    )
    subscription_id = uuid4()
    await executor.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, "
            "allocation_percent, status) "
            "VALUES (:id, :user_id, :strategy_id, :pool_id, :share, :status)"
        ),
        {
            "id": subscription_id,
            "user_id": author_id,
            "strategy_id": strategy_id,
            "pool_id": pool_id,
            "share": share,
            "status": status,
        },
    )
    return subscription_id


async def ensure_delivery(
    executor: AsyncConnection | AsyncSession,
    *,
    signal_id: UUID,
    strategy_id: UUID,
    user_id: UUID = OWNER_ID,
    subscription_strategy_id: UUID | None = None,
    delivery_id: UUID | None = None,
) -> UUID:
    """The id of the delivery of ``signal_id`` to ``user_id``'s subscription to
    ``strategy_id``, seeded when missing (multi-user design AD5; migration
    ``0032`` makes ``reservations.delivery_id`` NOT NULL).

    ``subscription_strategy_id`` hosts the subscription on another strategy, for a
    test that counts a strategy's subscriptions and must not see this one.

    ``delivery_id`` names a delivery that is made here (ignored when it exists):
    the single-subscriber unit tests run in a world where a delivery's id IS its
    signal's, and a real row needs that id.

    The user's live subscription is reused. A user with none gets an ENDED one,
    in their pool on the strategy's market: it serves only as the delivery's
    owner, and being ENDED it is never eligible for a signal and never blocks a
    later ``ACTIVE`` one (the partial unique ignores ENDED). A test about
    subscriptions seeds its own, before or after. Not committed."""
    hosting = strategy_id if subscription_strategy_id is None else subscription_strategy_id
    # A live subscription first, then one this helper made earlier (ENDED).
    known = (
        await executor.execute(
            text(
                "SELECT id FROM subscriptions WHERE user_id = :user_id "
                "AND strategy_id = :strategy_id ORDER BY (status = 'ENDED'), created_at LIMIT 1"
            ),
            {"user_id": user_id, "strategy_id": hosting},
        )
    ).scalar_one_or_none()
    if known is not None:
        subscription_id = UUID(str(known))
    else:
        market = (
            await executor.execute(
                text(
                    "SELECT exchange, venue, settlement_currency FROM strategies "
                    "WHERE id = :strategy_id"
                ),
                {"strategy_id": hosting},
            )
        ).one()
        pool_id = await ensure_pool(executor, (market[0], market[1], market[2]), user_id=user_id)
        subscription_id = uuid4()
        await executor.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, "
                "allocation_percent, status, ended_at) "
                "VALUES (:id, :user_id, :strategy_id, :pool_id, 30, 'ENDED', now())"
            ),
            {
                "id": subscription_id,
                "user_id": user_id,
                "strategy_id": hosting,
                "pool_id": pool_id,
            },
        )
    existing = (
        await executor.execute(
            text(
                "SELECT id FROM signal_deliveries "
                "WHERE signal_id = :signal_id AND subscription_id = :subscription_id"
            ),
            {"signal_id": signal_id, "subscription_id": subscription_id},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))
    delivery_id = delivery_id if delivery_id is not None else uuid4()
    await executor.execute(
        text(
            "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
            "VALUES (:id, :signal_id, :subscription_id, :user_id)"
        ),
        {
            "id": delivery_id,
            "signal_id": signal_id,
            "subscription_id": subscription_id,
            "user_id": user_id,
        },
    )
    return delivery_id


async def allocate_command(
    factory: async_sessionmaker[AsyncSession],
    *,
    signal_id: UUID,
    strategy_id: UUID,
    requested: Money,
    user_id: UUID = OWNER_ID,
) -> AllocateCommand:
    """The command that allocates ``signal_id`` for ``user_id``: the delivery it
    serves is seeded (``ensure_delivery``) and committed first, since the
    reservation it writes names it."""
    async with factory() as session:
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=user_id
        )
        await session.commit()
    return AllocateCommand(
        signal_id=signal_id,
        strategy_id=strategy_id,
        requested=requested,
        user_id=user_id,
        delivery_id=delivery_id,
    )


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
    delivery_id: UUID | None = None,
) -> int:
    """One ``reservations`` row of ``user_id``, in that user's pool on
    ``market`` (seeded when missing, ``ensure_pool``), written raw. Returns the
    pool's id. Not committed: the caller's transaction owns it.

    The reservation serves ``delivery_id``, or, when none is given, the delivery
    of its signal to the user's subscription (``ensure_delivery``)."""
    pool_id = await ensure_pool(executor, market, user_id=user_id)
    if delivery_id is None:
        delivery_id = await ensure_delivery(
            executor, signal_id=signal_id, strategy_id=strategy_id, user_id=user_id
        )
    exchange, venue, currency = market
    await executor.execute(
        text(
            "INSERT INTO reservations "
            "(id, user_id, pool_id, strategy_id, signal_id, delivery_id, exchange, venue, "
            "settlement_currency, amount, status, expires_at) "
            "VALUES (:id, :user_id, :pool_id, :strategy_id, :signal_id, :delivery_id, "
            ":exchange, :venue, "
            ":settlement_currency, :amount, :status, :expires_at)"
        ),
        {
            "id": reservation_id,
            "user_id": user_id,
            "pool_id": pool_id,
            "strategy_id": strategy_id,
            "delivery_id": delivery_id,
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


async def attempt_user_id(
    executor: AsyncConnection | AsyncSession,
    *,
    reservation_id: UUID | None,
    closes_allocation_id: UUID | None,
    user_id: UUID | None = None,
) -> UUID:
    """The user an ``execution_attempts`` seed is written as: ``user_id`` when
    given, else the user of the reservation the attempt spends (an open) or
    unwinds (a close), else the owner. That is how production writes it, so a
    seeded attempt and its reservation never disagree unless a test says so."""
    if user_id is not None:
        return user_id
    origin = reservation_id if reservation_id is not None else closes_allocation_id
    if origin is not None:
        found = (
            await executor.execute(
                text("SELECT user_id FROM reservations WHERE id = :id"), {"id": origin}
            )
        ).scalar_one_or_none()
        if found is not None:
            return UUID(str(found))
    return OWNER_ID


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
