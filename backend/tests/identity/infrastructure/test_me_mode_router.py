"""``POST /api/me/mode``: a user changes their own mode (multi-user design AD7,
decisions 6, 7, 14 and 26; tasks.md E.2).

Going live needs a trade-capable key. Going back to simulation is refused while
anything real is held, because a real position must stay where its close can
reach it. The brake refuses both directions: it forces simulation for everyone,
so a change made under it could not be honoured.

Mounted through ``create_app()`` with a real PostgreSQL session. The symbols are
spelled differently per table, as they are in production: the signal as
TradingView sends it, the attempt and the ledger as the venue does.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    FORGED_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import seed_reservation_row, seed_user

pytestmark = pytest.mark.integration

WAIT_SECONDS = 5.0
CHANGE_LOGGER = "strategy_manager.identity.application.change_mode"
GARBAGE =b"\x00not-a-real-ciphertext\xff"
CONFIRMED_AT = datetime(2026, 10, 1, tzinfo=UTC)


class World:
    """One signed-in user and what they hold."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], user_id: UUID) -> None:
        self.factory = factory
        self.user_id = user_id
        self._strategies: dict[UUID, UUID] = {}

    async def stored_mode(self) -> str:
        async with self.factory() as session:
            return str(
                (
                    await session.execute(
                        text("SELECT mode FROM users WHERE id = :id"), {"id": self.user_id}
                    )
                ).scalar_one()
            )

    async def key(
        self, *, trade_capable: bool = True, active: bool = True, exchange: str = "bybit"
    ) -> None:
        async with self.factory() as session:
            session.add(
                ExchangeCredentialRow(
                    user_id=self.user_id,
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
                    trade_capable=trade_capable,
                    trade_capability_source="VERIFIED",
                    withdraw_check="VERIFIED",
                    validated_at=CONFIRMED_AT,
                    internal_transfer=None,
                )
            )
            await session.commit()

    async def signal(self, symbol: str) -> tuple[UUID, UUID]:
        """A strategy of this user and one signal of it on ``symbol``."""
        strategy_id, signal_id = uuid4(), uuid4()
        await seed_strategy(self.factory, strategy_id=strategy_id, author_id=self.user_id)
        await seed_signal(
            self.factory,
            signal_id=signal_id,
            strategy_id=strategy_id,
            idempotency_key=f"k-{signal_id}",
        )
        async with self.factory() as session:
            await session.execute(
                text("UPDATE signals SET symbol = :symbol WHERE id = :id"),
                {"symbol": symbol, "id": signal_id},
            )
            await session.commit()
        return strategy_id, signal_id

    async def reservation(
        self, *, status: str = "PENDING", mode: str = "LIVE", symbol: str = "STXUSDT.P"
    ) -> UUID:
        strategy_id, signal_id = await self.signal(symbol)
        reservation_id = uuid4()
        await seed_reservation(
            self.factory,
            reservation_id=reservation_id,
            strategy_id=strategy_id,
            signal_id=signal_id,
            status=status,
            mode=mode,
            user_id=self.user_id,
        )
        self._strategies[reservation_id] = strategy_id
        return reservation_id

    async def fill(
        self,
        reservation_id: UUID,
        *,
        side: str = "BUY",
        rehearsal: bool = False,
        symbol: str = "STXUSDT",
    ) -> None:
        attempt_id = uuid4()
        closing = side == "SELL"
        await seed_execution_attempt(
            self.factory,
            attempt_id=attempt_id,
            reservation_id=None if closing else reservation_id,
            closes_allocation_id=reservation_id if closing else None,
            symbol=symbol,
            status="FILLED",
        )
        prefix = REHEARSAL_FILL_ID_PREFIX if rehearsal else "live-"
        async with self.factory() as session:
            await RecordFill(SqlAlchemyLedgerRepository(session)).record(
                FillRecord(
                    exchange="bybit",
                    user_id=self.user_id,
                    strategy_id=self._strategies[reservation_id],
                    allocation_id=reservation_id,
                    execution_attempt_id=attempt_id,
                    venue="usdt-m",
                    settlement_currency="USDT",
                    symbol=symbol,
                    side=side,
                    quantity=Decimal("1"),
                    price=Decimal("100"),
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    notional=Decimal("100"),
                    exchange_order_id=f"order-{uuid4()}",
                    exchange_fill_id=f"{prefix}{uuid4()}",
                    filled_at=CONFIRMED_AT,
                    usd_rate_at_fill=Decimal("1"),
                )
            )
            await session.commit()

    async def open_allocation(self, *, rehearsal: bool = False, symbol: str = "STXUSDT") -> UUID:
        mode = "SIMULATION" if rehearsal else "LIVE"
        reservation_id = await self.reservation(status="FILLED", mode=mode)
        await self.fill(reservation_id, rehearsal=rehearsal, symbol=symbol)
        return reservation_id


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture(autouse=True)
def _brake_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        await session.commit()
    return pg_session_factory


@pytest.fixture
async def client(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _user(factory: async_sessionmaker[AsyncSession], email: str, mode: str) -> World:
    async with factory() as session:
        user_id = await seed_user(session, email)
        await session.execute(
            text("UPDATE users SET mode = :mode WHERE id = :id"), {"mode": mode, "id": user_id}
        )
        await session.commit()
    return World(factory, user_id)


async def _until_waiting_on_a_row_lock(factory: async_sessionmaker[AsyncSession]) -> None:
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while True:
        async with factory() as session:
            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'transactionid' AND NOT granted"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("no backend ever waited on a row lock")
        await asyncio.sleep(0.02)


async def test_going_live_with_a_trade_capable_key_changes_the_mode(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")
    await world.key()

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 200
    assert response.json() == {
        "email": ADMIN_EMAIL,
        "is_admin": True,
        "mode": "LIVE",
        "dry_run_brake": False,
    }
    assert await world.stored_mode() == "LIVE"


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(None, id="no-key"),
        pytest.param({"trade_capable": False}, id="read-only"),
        pytest.param({"active": False}, id="superseded"),
    ],
)
async def test_going_live_without_an_active_trade_capable_key_is_refused(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    key: dict[str, bool] | None,
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")
    if key is not None:
        await world.key(**key)

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "MODE_LIVE_NEEDS_TRADE_KEY"
    assert await world.stored_mode() == "SIMULATION"


async def test_one_trade_capable_key_is_enough_beside_a_read_only_one(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")
    await world.key(trade_capable=False, exchange="pionex")
    await world.key(exchange="bybit")

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 200
    assert await world.stored_mode() == "LIVE"


async def test_another_users_key_does_not_let_this_user_go_live(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")
    other = await _user(factory, OTHER_EMAIL, "SIMULATION")
    await other.key()

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 409
    assert await world.stored_mode() == "SIMULATION"


async def test_going_live_with_simulated_positions_open_succeeds(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Decision 26: capital is counted per mode, so the simulated position closes
    in simulation and takes nothing from the real pool."""
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")
    await world.key()
    await world.open_allocation(rehearsal=True)
    await world.reservation(status="PENDING", mode="SIMULATION")

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 200
    assert await world.stored_mode() == "LIVE"


async def test_going_to_simulation_while_flat_changes_the_mode(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "SIMULATION"
    assert await world.stored_mode() == "SIMULATION"


def _change_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == CHANGE_LOGGER]


async def test_a_change_leaves_a_line_naming_the_user_and_the_new_mode(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """It decides where the user's next signal goes, so it does not pass in silence."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")

    with caplog.at_level(logging.INFO, logger=CHANGE_LOGGER):
        response = await client.post(
            "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
        )

    assert response.status_code == 200
    lines = _change_lines(caplog)
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO
    assert str(world.user_id) in lines[0].getMessage()
    assert "SIMULATION" in lines[0].getMessage()


async def test_a_refused_change_claims_nothing_in_the_log(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    await world.reservation(status="PENDING", symbol="STXUSDT.P")

    with caplog.at_level(logging.INFO, logger=CHANGE_LOGGER):
        response = await client.post(
            "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
        )

    assert response.status_code == 409
    assert _change_lines(caplog) == []


@pytest.mark.parametrize("status", ["PENDING", "SUBMITTED"])
async def test_a_live_reservation_refuses_going_to_simulation(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], status: str
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    await world.reservation(status=status, symbol="STXUSDT.P")

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "MODE_SIMULATION_NEEDS_FLAT"
    assert response.json()["detail"]["symbols"] == ["STXUSDT"]
    assert await world.stored_mode() == "LIVE"


async def test_a_live_reservation_past_its_expiry_still_refuses(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The sweeper has not reached it, so a worker may still be placing its order:
    ``expires_at`` says what capital is counted, not that nothing is happening."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    strategy_id, signal_id = await world.signal("STXUSDT.P")
    await seed_reservation(
        factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="SUBMITTED",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        user_id=world.user_id,
    )

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 409


async def test_a_live_open_allocation_refuses_going_to_simulation(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    await world.open_allocation(symbol="SOLUSDT")

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "MODE_SIMULATION_NEEDS_FLAT"
    assert response.json()["detail"]["symbols"] == ["SOLUSDT"]
    assert await world.stored_mode() == "LIVE"


async def test_a_submitted_live_attempt_with_no_order_id_yet_refuses(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The order may be on its way to the venue: nothing says it is not, and the
    allocation has no fill yet, so only the attempt shows it."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    reservation_id = await world.reservation(status="FILLED")
    await seed_execution_attempt(
        factory,
        attempt_id=uuid4(),
        reservation_id=reservation_id,
        symbol="ADAUSDT",
        status="SUBMITTED",
        exchange_order_id=None,
    )

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["symbols"] == ["ADAUSDT"]


async def test_a_submitted_closing_attempt_refuses_too(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """A closing attempt names the allocation it unwinds, not a reservation."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    allocation_id = await world.reservation(status="FILLED")
    await seed_execution_attempt(
        factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation_id,
        symbol="ADAUSDT",
        status="SUBMITTED",
    )

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["symbols"] == ["ADAUSDT"]


async def test_one_market_in_several_spellings_is_listed_once_and_sorted(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    await world.reservation(symbol="STXUSDT.P")
    await world.reservation(symbol="ADAUSDT.P")
    await world.open_allocation(symbol="STXUSDT")
    await world.open_allocation(symbol="STXUSDT_PERP")

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.json()["detail"]["symbols"] == ["ADAUSDT", "STXUSDT"]


async def test_nothing_real_held_lets_the_user_go_to_simulation(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """A closed real allocation, finished reservations and everything simulated:
    none of it can reach a venue any more."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    closed = await world.open_allocation()
    await world.fill(closed, side="SELL")
    await world.reservation(status="RELEASED")
    await world.reservation(status="EXPIRED")
    await world.reservation(status="FILLED")
    await world.reservation(status="SUBMITTED", mode="SIMULATION")
    await world.open_allocation(rehearsal=True)
    simulated = await world.reservation(status="FILLED", mode="SIMULATION")
    await seed_execution_attempt(
        factory, attempt_id=uuid4(), reservation_id=simulated, status="SUBMITTED"
    )

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 200
    assert await world.stored_mode() == "SIMULATION"


@pytest.mark.parametrize(
    ("stored", "asked"), [("SIMULATION", "LIVE"), ("LIVE", "SIMULATION")]
)
async def test_the_brake_refuses_either_direction(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    stored: str,
    asked: str,
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", True)
    world = await _user(factory, ADMIN_EMAIL, stored)
    await world.key()

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": asked})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "MODE_BRAKE_ON"
    assert await world.stored_mode() == stored


async def test_a_user_changes_only_their_own_mode(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    other = await _user(factory, OTHER_EMAIL, "SIMULATION")
    await other.key()

    response = await client.post("/api/me/mode", headers=OTHER_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 200
    assert response.json()["email"] == OTHER_EMAIL
    assert await other.stored_mode() == "LIVE"
    assert await world.stored_mode() == "LIVE"


async def test_another_users_real_position_refuses_nobody_else(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    other = await _user(factory, OTHER_EMAIL, "LIVE")
    await other.open_allocation()
    await other.reservation()
    await seed_execution_attempt(
        factory,
        attempt_id=uuid4(),
        reservation_id=await other.reservation(status="FILLED"),
        status="SUBMITTED",
    )

    response = await client.post(
        "/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"}
    )

    assert response.status_code == 200
    assert await world.stored_mode() == "SIMULATION"
    assert await other.stored_mode() == "LIVE"


async def test_the_change_waits_for_an_opening_in_flight_and_then_sees_it(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The opening holds the user row ``FOR SHARE`` until its reservation commits
    (``SqlAlchemyUserMode``). Without the row lock the flat check would pass
    beside it and a real reservation would appear after the user went to
    simulation."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    strategy_id, signal_id = await world.signal("STXUSDT.P")

    task: asyncio.Task[object] | None = None
    async with factory() as opening:
        await opening.execute(
            select(UserRow.id).where(UserRow.id == world.user_id).with_for_update(read=True)
        )
        await seed_reservation_row(
            opening,
            reservation_id=uuid4(),
            strategy_id=strategy_id,
            signal_id=signal_id,
            status="PENDING",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            user_id=world.user_id,
        )
        task = asyncio.create_task(
            client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"})
        )
        try:
            await _until_waiting_on_a_row_lock(factory)
            assert not task.done(), "the change finished while the opening held the user row"
            await opening.commit()
            response = await asyncio.wait_for(task, WAIT_SECONDS)
        finally:
            if not task.done():
                task.cancel()

    assert response.status_code == 409  # type: ignore[attr-defined]
    assert response.json()["detail"]["symbols"] == ["STXUSDT"]  # type: ignore[attr-defined]
    assert await world.stored_mode() == "LIVE"


async def test_what_is_still_in_flight_is_read_before_the_ledger(
    factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine  # noqa: F811
) -> None:
    """Each read is its own snapshot, and a settle moves the exposure from the
    reservation and the attempt to the ledger in one commit. Reading the ledger
    first could miss the fill and then miss the attempt it replaced, and the user
    would read as flat with a real position open."""
    world = await _user(factory, ADMIN_EMAIL, "LIVE")
    statements: list[str] = []

    def record(
        conn: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", record)
    try:
        async with factory() as session:
            await SqlAlchemyLiveExposure(session).symbols(world.user_id)
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", record)

    tables = ["FROM reservations", "FROM execution_attempts", "FROM ledger_entries"]
    firsts = [
        next(i for i, statement in enumerate(statements) if table in statement)
        for table in tables
    ]
    assert firsts == sorted(firsts)


async def test_a_mode_that_does_not_exist_is_refused_by_the_body(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await _user(factory, ADMIN_EMAIL, "SIMULATION")

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "live"})

    assert response.status_code == 422
    assert await world.stored_mode() == "SIMULATION"


@pytest.mark.parametrize("headers", [{}, FORGED_HEADERS])
async def test_no_identity_is_401(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], headers: dict[str, str]
) -> None:
    response = await client.post("/api/me/mode", headers=headers, json={"mode": "LIVE"})

    assert response.status_code == 401
