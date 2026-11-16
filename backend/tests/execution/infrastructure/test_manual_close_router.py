"""``POST /api/positions/{allocation_id}/close`` on a real PostgreSQL database
(subscriber-safety SS.9, spec ``safety-close``, "A user can close their own position from the
panel").

The API never opens a key, so it never places the order: it checks that the allocation is the
signed-in user's, enqueues one ``execution.manual_close`` job and answers 202. Mounted through
``create_app()`` so the ``/api`` prefix and the router's sign-in guard are part of what is
proven, with ``get_session`` overridden to a real session.

* another user's allocation, an unknown id and a flat one answer 404 and enqueue nothing;
* a close of the allocation that is SUBMITTED answers 202 ``ALREADY_IN_FLIGHT`` and enqueues
  nothing;
* a double click enqueues once, and a retry after a FAILED close enqueues again.
"""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.application.job import JobKind
from tests.execution.infrastructure.conftest import seed_execution_attempt
from tests.execution.infrastructure.test_stopped_positions_reader import (
    _allocation,
    _strategy,
)
from tests.identity_auth import ADMIN_HEADERS, FORGED_HEADERS, seed_admin, sign_in_as_admin
from tests.owner import seed_other_user

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def client(pg_session_factory: Factory) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _admin_id(factory: Factory) -> UUID:
    async with factory() as session:
        admin = await seed_admin(session)
        await session.commit()
    return admin


async def _held(factory: Factory, user_id: UUID, quantity: str = "76") -> UUID:
    strategy = await _strategy(factory, enabled=True)
    return await _allocation(
        factory, user_id, strategy, [("BUY", "DOGEUSDT.P", quantity, "0.1", "USDT")]
    )


async def _jobs(factory: Factory) -> list[tuple[str, dict[str, str], str | None]]:
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT kind, payload, dedupe_key FROM jobs WHERE kind = :kind "
                "ORDER BY created_at"
            ),
            {"kind": JobKind.MANUAL_CLOSE.value},
        )
        return [(row[0], row[1], row[2]) for row in rows.all()]


def _url(allocation_id: UUID) -> str:
    return f"/api/positions/{allocation_id}/close"


async def test_an_own_allocation_queues_exactly_one_job(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)

    response = await client.post(_url(allocation), headers=ADMIN_HEADERS)

    assert response.status_code == 202
    assert response.json() == {"status": "QUEUED"}
    [(kind, payload, dedupe_key)] = await _jobs(pg_session_factory)
    assert kind == "execution.manual_close"
    assert payload == {"user_id": str(admin), "allocation_id": str(allocation)}
    assert dedupe_key == f"manual_close:{allocation}:none"


async def test_another_users_allocation_is_not_found_and_queues_nothing(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    await _admin_id(pg_session_factory)
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    theirs = await _held(pg_session_factory, other)

    response = await client.post(_url(theirs), headers=ADMIN_HEADERS)

    assert response.status_code == 404
    assert await _jobs(pg_session_factory) == []


async def test_an_unknown_allocation_is_not_found_and_queues_nothing(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    await _admin_id(pg_session_factory)

    response = await client.post(_url(uuid4()), headers=ADMIN_HEADERS)

    assert response.status_code == 404
    assert await _jobs(pg_session_factory) == []


async def test_a_flat_allocation_is_not_found_and_queues_nothing(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    strategy = await _strategy(pg_session_factory, enabled=True)
    flat = await _allocation(
        pg_session_factory,
        admin,
        strategy,
        [
            ("BUY", "DOGEUSDT.P", "76", "0.1", "USDT"),
            ("SELL", "DOGEUSDT", "76", "0.1", "USDT"),
        ],
    )

    response = await client.post(_url(flat), headers=ADMIN_HEADERS)

    assert response.status_code == 404
    assert await _jobs(pg_session_factory) == []


async def test_a_close_in_flight_answers_already_in_flight_and_queues_nothing(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation,
        symbol="DOGEUSDT",
        status="SUBMITTED",
    )

    response = await client.post(_url(allocation), headers=ADMIN_HEADERS)

    assert response.status_code == 202
    assert response.json() == {"status": "ALREADY_IN_FLIGHT"}
    assert await _jobs(pg_session_factory) == []


async def test_a_double_click_leaves_exactly_one_job(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)

    first = await client.post(_url(allocation), headers=ADMIN_HEADERS)
    second = await client.post(_url(allocation), headers=ADMIN_HEADERS)

    assert (first.status_code, second.status_code) == (202, 202)
    assert len(await _jobs(pg_session_factory)) == 1


async def test_a_new_request_after_a_failed_close_queues_again(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)
    await client.post(_url(allocation), headers=ADMIN_HEADERS)
    failed = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=failed,
        closes_allocation_id=allocation,
        symbol="DOGEUSDT",
        status="FAILED",
    )

    response = await client.post(_url(allocation), headers=ADMIN_HEADERS)

    assert response.status_code == 202
    assert response.json() == {"status": "QUEUED"}
    jobs = await _jobs(pg_session_factory)
    assert [key for _, _, key in jobs] == [
        f"manual_close:{allocation}:none",
        f"manual_close:{allocation}:{failed}",
    ]


async def test_a_job_that_finished_without_closing_does_not_block_the_next_request(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    """A job that ended without an attempt (no key could sign, the ledger was not settled
    yet) keeps its dedupe key until the purge, days later. The button must not go dead
    for that long: a finished job's key is released, and only a live one dedupes."""
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)
    await client.post(_url(allocation), headers=ADMIN_HEADERS)
    async with pg_session_factory() as session:
        await session.execute(text("UPDATE jobs SET status = 'DONE' WHERE kind = :kind"),
                              {"kind": JobKind.MANUAL_CLOSE.value})
        await session.commit()

    response = await client.post(_url(allocation), headers=ADMIN_HEADERS)

    assert response.json() == {"status": "QUEUED"}
    async with pg_session_factory() as session:
        live = (
            await session.execute(
                text("SELECT count(*) FROM jobs WHERE kind = :kind AND status = 'PENDING'"),
                {"kind": JobKind.MANUAL_CLOSE.value},
            )
        ).scalar_one()
    assert live == 1


async def test_a_request_without_a_valid_sign_in_is_refused(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    admin = await _admin_id(pg_session_factory)
    allocation = await _held(pg_session_factory, admin)

    missing = await client.post(_url(allocation))
    forged = await client.post(_url(allocation), headers=FORGED_HEADERS)

    assert (missing.status_code, forged.status_code) == (401, 401)
    assert await _jobs(pg_session_factory) == []


async def test_a_malformed_allocation_id_is_a_validation_error(
    client: AsyncClient, pg_session_factory: Factory
) -> None:
    await _admin_id(pg_session_factory)

    response = await client.post("/api/positions/not-a-uuid/close", headers=ADMIN_HEADERS)

    assert response.status_code == 422
    assert await _jobs(pg_session_factory) == []
