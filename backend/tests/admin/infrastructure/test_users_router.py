"""``GET /api/admin/users`` (tasks.md F.7, decision 8), on real PostgreSQL.

``users`` outlives the integration fixtures' truncates, so a test finds its own
users by a unique e-mail and never counts the whole list.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, FORGED_HEADERS, OTHER_HEADERS, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import seed_pool, seed_snapshot, seed_user
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

USERS = "/api/admin/users"

BYBIT = ("bybit", "usdt-m", "USDT")
BINANCE = ("binance", "usdt-m", "USDT")

GARBAGE = b"\x00not-a-real-ciphertext\xff"
CONFIRMED_AT = datetime(2026, 10, 1, tzinfo=UTC)

#: A body is an explicit list: no amount and no performance can reach it unnoticed.
BODY_KEYS = {
    "email",
    "display_name",
    "mode",
    "exchanges_with_key",
    "exchanges_with_no_key",
    "subscriptions",
    "open_positions",
    "last_seen_at",
    "identity",
    "id",
    "suspended_at",
}

#: The identity the sign-up form gave, as the privacy policy says the admin sees it
#: (public-site LS3): nothing of the declarations or the acceptance record.
IDENTITY_KEYS = {"first_name", "last_name", "cuit", "country"}


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def admin(
    pg_session_factory: Factory,  # noqa: F811
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=ADMIN_HEADERS
    ) as client:
        yield client


async def _user(factory: Factory, prefix: str = "user") -> tuple[UUID, str]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    async with factory() as session:
        user_id = await seed_user(session, email)
        await session.commit()
    return user_id, email


async def _pool(
    factory: Factory,
    user_id: UUID,
    market: tuple[str, str, str] = BYBIT,
    *,
    enabled: bool = True,
) -> int:
    async with factory() as session:
        pool_id = await seed_pool(session, market, user_id=user_id, enabled=enabled)
        await session.commit()
    return pool_id


async def _key(factory: Factory, user_id: UUID, exchange: str, *, active: bool = True) -> None:
    # Bybit's capability is read from the venue, Binance's is confirmed by hand.
    confirmed = exchange == "binance"
    source = "OWNER_CONFIRMED" if confirmed else "VERIFIED"
    async with factory() as session:
        session.add(
            ExchangeCredentialRow(
                user_id=user_id,
                exchange=exchange,
                label="default",
                is_active=active,
                wrapped_dek=GARBAGE,
                dek_nonce=GARBAGE,
                api_key_ciphertext=GARBAGE,
                api_key_nonce=GARBAGE,
                api_secret_ciphertext=GARBAGE,
                api_secret_nonce=GARBAGE,
                api_key_last4="abcd",
                trade_capable=True,
                trade_capability_source=source,
                trade_confirmed_at=CONFIRMED_AT if confirmed else None,
                withdraw_check=source,
                withdraw_confirmed_at=CONFIRMED_AT if confirmed else None,
                validated_at=CONFIRMED_AT,
                internal_transfer=None,
            )
        )
        await session.commit()


async def _flatten(factory: Factory, user_id: UUID) -> None:
    """Sell what the user's only ledger entry bought, so its allocation nets to zero."""
    async with factory() as session:
        bought = (
            await session.execute(select(LedgerEntryRow).where(LedgerEntryRow.user_id == user_id))
        ).scalar_one()
        entry_id = uuid4()
        session.add(
            LedgerEntryRow(
                id=entry_id,
                user_id=user_id,
                strategy_id=bought.strategy_id,
                allocation_id=bought.allocation_id,
                execution_attempt_id=bought.execution_attempt_id,
                exchange=bought.exchange,
                venue=bought.venue,
                settlement_currency=bought.settlement_currency,
                symbol=bought.symbol,
                side="SELL",
                quantity=bought.quantity,
                price=bought.price,
                fee=Decimal("0"),
                fee_currency=bought.fee_currency,
                notional=bought.notional,
                exchange_order_id=f"order-{entry_id}",
                exchange_fill_id=f"fill-{entry_id}",
                filled_at=datetime.now(UTC),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()


async def _listed(admin: AsyncClient) -> list[dict[str, Any]]:
    response = await admin.get(USERS)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def _state_of(admin: AsyncClient, email: str) -> dict[str, Any]:
    found = [each for each in await _listed(admin) if each["email"] == email]
    assert len(found) == 1, f"{email} is listed {len(found)} times"
    return found[0]


async def test_a_user_is_listed_with_their_name_mode_and_last_sign_in(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    seen = datetime(2026, 10, 30, 12, 34, 56, tzinfo=UTC)
    name = f"Ana {uuid4().hex[:8]}"
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET display_name = :name, mode = 'LIVE', last_seen_at = :seen "
                "WHERE id = :id"
            ),
            {"name": name, "seen": seen, "id": user_id},
        )
        await session.commit()

    state = await _state_of(admin, email)

    assert state["display_name"] == name
    assert state["mode"] == "LIVE"
    assert state["last_seen_at"] == "2026-10-30T12:34:56Z"


async def test_a_new_user_has_no_name_nothing_held_and_simulation(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    _, email = await _user(pg_session_factory)

    state = await _state_of(admin, email)

    assert state["display_name"] is None
    assert state["mode"] == "SIMULATION"
    assert state["exchanges_with_key"] == []
    assert state["exchanges_with_no_key"] == []
    assert state["subscriptions"] == 0
    assert state["open_positions"] == 0
    assert state.get("identity", "no identity field") is None


async def test_a_signed_up_user_is_listed_with_the_identity_they_gave(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    other_id, other_email = await _user(pg_session_factory)
    async with pg_session_factory() as session:
        for each, first, last, cuit in (
            (user_id, "Ana María", "Pérez", "20123456786"),
            (other_id, "Juan", "Gómez", "27111111117"),
        ):
            await session.execute(
                text(
                    "UPDATE users SET first_name = :first, last_name = :last, cuit = :cuit, "
                    "country = 'AR', adult_declared_at = now(), truthful_declared_at = now() "
                    "WHERE id = :id"
                ),
                {"first": first, "last": last, "cuit": cuit, "id": each},
            )
        await session.commit()

    identity = (await _state_of(admin, email)).get("identity")
    other = (await _state_of(admin, other_email)).get("identity") or {}

    assert identity == {
        "first_name": "Ana María",
        "last_name": "Pérez",
        "cuit": "20123456786",
        "country": "AR",
    }
    assert set(identity) == IDENTITY_KEYS
    assert other["cuit"] == "27111111117"
    assert other["last_name"] == "Gómez"


async def test_another_user_is_not_shown_anyones_identity(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    """The list is the admin's alone: a signed-in user who is not the admin is
    refused, and the body names no CUIT."""
    user_id, _ = await _user(pg_session_factory)
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET first_name = 'Ana', last_name = 'Pérez', "
                "cuit = '20123456786', country = 'AR', adult_declared_at = now(), "
                "truthful_declared_at = now() WHERE id = :id"
            ),
            {"id": user_id},
        )
        await session.commit()

    response = await admin.get(USERS, headers=OTHER_HEADERS)

    assert response.status_code == 403, response.text
    assert "20123456786" not in response.text


async def test_no_assertion_or_a_forged_one_gets_no_identity(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Kept from the independent verifier's probe (PS.16): without a valid
    assertion the list answers 401, and no CUIT is in the body. Two guards give
    that 401, ``require_admin`` and the snapshot session's ``current_user``: it
    goes red only with both removed. ``OTHER_HEADERS`` above pins the first."""
    user_id, _ = await _user(pg_session_factory)
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET first_name = 'Ana', last_name = 'Pérez', "
                "cuit = '20123456786', country = 'AR', adult_declared_at = now(), "
                "truthful_declared_at = now() WHERE id = :id"
            ),
            {"id": user_id},
        )
        await session.commit()
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bare:
        for headers in ({}, FORGED_HEADERS):
            response = await bare.get(USERS, headers=headers)

            assert response.status_code == 401, response.text
            assert "20123456786" not in response.text


async def test_the_body_holds_no_amount_and_no_performance(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    """A user with a balance, a share and a position: none of the three reaches
    the wire, by the keys and by the text."""
    user_id, email = await _user(pg_session_factory)
    pool_id = await _pool(pg_session_factory, user_id)
    async with pg_session_factory() as session:
        await seed_snapshot(
            session,
            BYBIT,
            total=Decimal("7654321"),
            available=Decimal("6543217"),
            observed_at=datetime.now(UTC),
            user_id=user_id,
        )
        await session.commit()
    strategy_id = await seeds.strategy(pg_session_factory, author_id=user_id)
    # 61 is no clock's seconds, so a timestamp in the body cannot spell the share.
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id, share="61.75")
    await seeds.open_allocation(pg_session_factory, user_id, strategy_id)

    response = await admin.get(USERS)

    assert response.status_code == 200, response.text
    assert set((await _state_of(admin, email)).keys()) == BODY_KEYS
    assert "7654321" not in response.text
    assert "6543217" not in response.text
    assert "61.75" not in response.text


async def test_no_answer_of_the_list_is_kept_by_a_browser_or_a_proxy(
    admin: AsyncClient,
) -> None:
    """It names every e-mail. A refusal goes through the same door, so it is asked too."""
    answered = await admin.get(USERS)
    refused = await admin.get(USERS, headers=OTHER_HEADERS)

    assert answered.status_code == 200, answered.text
    assert refused.status_code == 403, refused.text
    assert answered.headers.get("cache-control") == "no-store"
    assert refused.headers.get("cache-control") == "no-store"


async def test_the_exchanges_with_an_active_key_are_listed_in_order(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    await _key(pg_session_factory, user_id, "bybit")
    await _key(pg_session_factory, user_id, "binance")

    state = await _state_of(admin, email)

    assert state["exchanges_with_key"] == ["binance", "bybit"]
    assert state["exchanges_with_no_key"] == []


async def test_a_superseded_key_lists_nothing(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    await _key(pg_session_factory, user_id, "bybit", active=False)
    await _key(pg_session_factory, user_id, "bybit")
    await _key(pg_session_factory, user_id, "binance", active=False)

    state = await _state_of(admin, email)

    assert state["exchanges_with_key"] == ["bybit"]


async def test_an_enabled_pool_with_no_active_key_is_told_apart(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    await _pool(pg_session_factory, user_id, BYBIT)
    await _key(pg_session_factory, user_id, "bybit", active=False)

    state = await _state_of(admin, email)

    assert state["exchanges_with_key"] == []
    assert state["exchanges_with_no_key"] == ["bybit"]


async def test_a_pool_with_its_key_is_not_told_apart(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    await _pool(pg_session_factory, user_id, BYBIT)
    await _key(pg_session_factory, user_id, "bybit")

    state = await _state_of(admin, email)

    assert state["exchanges_with_key"] == ["bybit"]
    assert state["exchanges_with_no_key"] == []


async def test_a_deleted_key_leaves_a_disabled_pool_and_shows_in_neither_list(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    """Deleting a key disables its pool, which is a user who left, not a fault."""
    user_id, email = await _user(pg_session_factory)
    await _pool(pg_session_factory, user_id, BYBIT, enabled=False)
    await _key(pg_session_factory, user_id, "bybit", active=False)

    state = await _state_of(admin, email)

    assert state["exchanges_with_key"] == []
    assert state["exchanges_with_no_key"] == []


async def test_one_users_key_does_not_cover_another_users_pool(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    holder, holder_email = await _user(pg_session_factory)
    other, other_email = await _user(pg_session_factory)
    await _key(pg_session_factory, holder, "bybit")
    await _pool(pg_session_factory, other, BYBIT)

    assert (await _state_of(admin, holder_email))["exchanges_with_key"] == ["bybit"]
    assert (await _state_of(admin, other_email))["exchanges_with_key"] == []
    assert (await _state_of(admin, other_email))["exchanges_with_no_key"] == ["bybit"]


async def test_active_and_leaving_subscriptions_count_and_ended_ones_do_not(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    other, other_email = await _user(pg_session_factory)
    pool_id = await _pool(pg_session_factory, user_id)
    other_pool = await _pool(pg_session_factory, other)
    for status in ("ACTIVE", "LEAVING", "ENDED"):
        strategy_id = await seeds.strategy(pg_session_factory)
        await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id, status=status)
    await seeds.subscription(
        pg_session_factory, other, await seeds.strategy(pg_session_factory), other_pool
    )

    assert (await _state_of(admin, email))["subscriptions"] == 2
    assert (await _state_of(admin, other_email))["subscriptions"] == 1


async def test_an_open_allocation_counts_and_one_that_nets_to_zero_does_not(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    holding, holding_email = await _user(pg_session_factory)
    flat, flat_email = await _user(pg_session_factory)
    await _pool(pg_session_factory, holding)
    await _pool(pg_session_factory, flat)
    strategy_id = await seeds.strategy(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, holding, strategy_id, symbol="STXUSDT")
    await seeds.open_allocation(pg_session_factory, holding, strategy_id, symbol="SOLUSDT")
    await seeds.open_allocation(pg_session_factory, flat, strategy_id)
    await _flatten(pg_session_factory, flat)

    assert (await _state_of(admin, holding_email))["open_positions"] == 2
    assert (await _state_of(admin, flat_email))["open_positions"] == 0


async def test_the_list_is_ordered_by_email(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    _, second = await _user(pg_session_factory, "zz-second")
    _, first = await _user(pg_session_factory, "aa-first")

    emails = [each["email"] for each in await _listed(admin)]

    assert emails == sorted(emails)
    assert emails.index(first) < emails.index(second)


# --- deleted accounts (account-deletion S6) ----------------------------------------


async def _delete(factory: Factory, user_id: UUID) -> None:
    """What ``DeleteAccount`` leaves of the row."""
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE users SET email = 'deleted-' || id::text || '@invalid', "
                "display_name = NULL, deleted_at = now() WHERE id = :id"
            ),
            {"id": user_id},
        )
        await session.commit()


async def _deleted_count(admin: AsyncClient) -> int:
    response = await admin.get(f"{USERS}/deleted-count")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"deleted_accounts"}
    count: int = response.json()["deleted_accounts"]
    return count


async def test_a_deleted_account_is_left_out_of_the_list(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    _, kept = await _user(pg_session_factory)
    await _delete(pg_session_factory, user_id)

    emails = [each["email"] for each in await _listed(admin)]

    assert email not in emails
    assert f"deleted-{user_id}@invalid" not in emails
    assert kept in emails


async def test_the_deleted_accounts_are_counted_and_only_they(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    before = await _deleted_count(admin)
    first, _ = await _user(pg_session_factory)
    second, _ = await _user(pg_session_factory)
    await _user(pg_session_factory)

    await _delete(pg_session_factory, first)
    await _delete(pg_session_factory, second)

    assert await _deleted_count(admin) == before + 2


async def test_the_count_is_the_admins_alone(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    response = await admin.get(f"{USERS}/deleted-count", headers=OTHER_HEADERS)

    assert response.status_code == 403


# --- statements ------------------------------------------------------------------


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def _busy_user(factory: Factory) -> None:
    """A user with a pool, a key, a subscription and an open position."""
    user_id, _ = await _user(factory)
    pool_id = await _pool(factory, user_id)
    await _key(factory, user_id, "bybit")
    strategy_id = await seeds.strategy(factory, author_id=user_id)
    await seeds.subscription(factory, user_id, strategy_id, pool_id)
    await seeds.open_allocation(factory, user_id, strategy_id)


async def _sql_of_the_list(admin: AsyncClient, engine: AsyncEngine) -> list[str]:
    # The sign-in's own statements are not the read's: the admin's row exists first.
    assert (await admin.get(USERS)).status_code == 200
    with _captured_sql(engine) as statements:
        response = await admin.get(USERS)
    assert response.status_code == 200, response.text
    return list(statements)


async def test_the_statement_count_does_not_grow_with_the_users(
    pg_session_factory: Factory,  # noqa: F811
    pg_engine: AsyncEngine,  # noqa: F811
    admin: AsyncClient,
) -> None:
    await _busy_user(pg_session_factory)
    one = await _sql_of_the_list(admin, pg_engine)

    for _ in range(9):
        await _busy_user(pg_session_factory)
    ten = await _sql_of_the_list(admin, pg_engine)

    assert len(ten) == len(one), "the number of statements grew with the number of users"


async def test_the_read_runs_in_one_read_only_snapshot(
    pg_session_factory: Factory,  # noqa: F811
    pg_engine: AsyncEngine,  # noqa: F811
    admin: AsyncClient,
) -> None:
    await _busy_user(pg_session_factory)

    statements = await _sql_of_the_list(admin, pg_engine)

    transaction = [each for each in statements if "SET TRANSACTION" in each]
    assert transaction == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
    read = statements[statements.index(transaction[0]) :]
    assert len(read) == 5, "the snapshot, the users, the coverage, the subscriptions, the ledger"
