"""API tests for ``GET /reconciliation/discrepancies``.

Two things travel together here, exactly like
``tests/strategies/infrastructure/test_router_auth.py``: the bearer-token
guard (now shared, see ``shared/infrastructure/admin_auth.py``) refuses every
request without a valid token, discovered from the router itself rather than
a hand-written list; and, once authenticated, the endpoint reads real rows
back through ``SqlAlchemyDiscrepancyRepository`` rather than a fake -- the
whole point of decision 10 is that the router is a thin read over the port
Unit 1 already built and proved.

The trap this file is written to avoid: a row is confirmed NOW when
``status == 'CONFIRMED'``, never when ``confirmed_at IS NOT NULL`` (migration
``0020``); and "open" means ``resolved_at IS NULL``, a completely different
column from ``status``. The ``status`` QUERY parameter this endpoint accepts
(``open``/``resolved``/``all``) filters on ``resolved_at``; it has nothing to
do with the ``DiscrepancyStatus`` the response body's own ``status`` field
carries.
"""

import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.infrastructure.models import LedgerEntryRow  # noqa: F401
from strategy_manager.main import create_app
from strategy_manager.reconciliation.application.ports import (
    NewBookingProposal,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.reconciliation.infrastructure.conftest import (
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

#: The pool every booking-proposal test below seeds and books against.
_BOOKING_POOL = ("bybit", "usdt-m", "USDT")

TOKEN = "adm1n-t0ken"
NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)

#: Path parameters are filled with a well-formed value so that a refusal is
#: never the path converter's doing.
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) this router serves, read from the router itself
    -- exactly the pattern ``test_router_auth.py`` uses for ``/strategies``."""
    pairs: list[tuple[str, str]] = []
    for route in reconciliation_router.routes:
        path = _PATH_PARAM.sub(str(uuid4()), getattr(route, "path", ""))
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            pairs.append((method, path))
    return pairs


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(reconciliation_router)
    return app


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    yield


@pytest.fixture(autouse=True)
def _configure_dry_run_false(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``Settings.dry_run`` defaults to ``True`` (the safe position) --
    every Unit 7 test below exercises the REAL branch, mirroring
    ``test_approve_booking_integration.py``'s own ``dry_run: bool = False``
    default. The two DRY_RUN-specific tests override this back to ``True``
    locally."""
    monkeypatch.setattr(get_settings(), "dry_run", False)
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


async def test_reconciliation_routes_live_under_api_prefix() -> None:
    """The ``/api`` move (design.md §13, spec: admin-api). In the real
    composition root, ``/reconciliation`` now resolves under
    ``/api/reconciliation`` — still refused without a token, structural per
    router exactly as the rest of this file already proves for the bare
    ``_app()`` above — and the pre-move path is no longer registered at all.

    Uses ``create_app()`` rather than this file's own bare ``_app()``/
    ``client`` fixture on purpose: those exist to test the router's own
    dependency in isolation, mount-independent, and every other test in this
    file keeps calling the unprefixed path against that same isolated mount.
    This is the one test that proves where ``main.py`` actually mounts it.
    Proven by live requests rather than by inspecting ``app.routes`` — this
    FastAPI version resolves an included router's routes lazily
    (``_IncludedRouter``), so the table is not flat until a request actually
    walks it.
    """
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        under_api = await api.get("/api/reconciliation/discrepancies")
        assert under_api.status_code == 401

        pre_move = await api.get("/reconciliation/discrepancies")
        assert pre_move.status_code == 404


async def _authenticated_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    from strategy_manager.shared import db as shared_db

    # ``booking_proposals`` (migration ``0023``) has no ORM-level FK to
    # ``reconciliation_discrepancies`` -- ``BookingProposalRow``'s own
    # docstring: the migration owns every table-level constraint, this
    # mapping is column shape only. So ``pg_engine``'s own
    # ``TRUNCATE reconciliation_discrepancies CASCADE`` never reaches this
    # table, and every Unit 7 test below writes proposals that would
    # otherwise leak into the NEXT test's ``list_pending`` results.
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE booking_proposals"))
        await session.commit()

    app = _app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


@pytest.fixture
async def authenticated_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async for api in _authenticated_client(pg_session_factory):
        yield api


def _observation(
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    venue_net_base: Decimal = Decimal("2.0"),
    ledger_net_base: Decimal = Decimal("1.5"),
) -> Observation:
    return Observation(kind=kind, venue_net_base=venue_net_base, ledger_net_base=ledger_net_base)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pool: tuple[str, str, str],
    symbol: str,
    status: DiscrepancyStatus = DiscrepancyStatus.OBSERVED,
    resolve: bool = False,
    observation: Observation | None = None,
) -> None:
    scan_id = uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            pool,
            symbol,
            observation or _observation(),
            [uuid4()],
            consecutive_scans=1,
            status=status,
            scan_id=scan_id,
            at=NOW,
        )
        if resolve:
            await repo.resolve_absent(pool, [symbol], scan_id, NOW)
        await session.commit()


async def test_there_is_at_least_one_route_to_protect() -> None:
    """Guards the enumeration itself: a test that iterates an empty list
    passes while proving nothing."""
    assert len(_routes()) >= 1


async def test_every_registered_route_refuses_a_request_without_a_token(
    client: AsyncClient,
) -> None:
    for method, path in _routes():
        response = await client.request(method, path)

        assert response.status_code == 401, f"{method} {path} was not refused"


async def test_no_route_leaks_which_part_of_the_credential_was_wrong(
    client: AsyncClient,
) -> None:
    details = set()
    for method, path in _routes():
        for headers in (
            {},
            {"Authorization": f"Bearer {TOKEN}-wrong"},
            {"Authorization": TOKEN},
        ):
            response = await client.request(method, path, headers=headers)

            assert response.status_code == 401
            details.add(response.json()["detail"])

    assert details == {UNAUTHORIZED_DETAIL}


async def test_authenticated_admin_lists_open_discrepancies_across_pools(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    """The spec scenario: two open discrepancies across different pools,
    both listed, each naming its pool and symbol."""
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="BTCUSDT",
    )
    await _seed(
        pg_session_factory,
        pool=("binance", "usdt-m", "USDT"),
        symbol="ETHUSDT",
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    pools_and_symbols = {
        (row["exchange"], row["venue"], row["settlement_currency"], row["symbol"])
        for row in body
    }
    assert pools_and_symbols == {
        ("bybit", "usdt-m", "USDT", "BTCUSDT"),
        ("binance", "usdt-m", "USDT", "ETHUSDT"),
    }


async def test_nets_read_back_at_scale_18_are_written_in_plain_notation(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    """``Numeric(38, 18)`` reads a zero back as ``Decimal("0E-18")``, whose
    ``str`` is ``"0E-18"``: a full close (venue net 0) must not reach the wire so."""
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="ZEROUSDT",
        observation=_observation(
            venue_net_base=Decimal("0"), ledger_net_base=Decimal("0")
        ),
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    [row] = response.json()
    assert row["venue_net_base"] == "0.000000000000000000"
    assert row["ledger_net_base"] == "0.000000000000000000"


async def test_default_status_filter_excludes_resolved_discrepancies(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["OPENCOIN"]


async def test_status_resolved_returns_only_resolved_discrepancies(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    """The trap this test exists to catch: filtering must key on
    ``resolved_at``, never on the CONFIRMED/OBSERVED ``status`` column."""
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"status": "resolved"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["RESOLVEDCOIN"]


async def test_status_all_returns_both_open_and_resolved(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"status": "all"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert {row["symbol"] for row in response.json()} == {"OPENCOIN", "RESOLVEDCOIN"}


async def test_limit_bounds_the_number_of_rows_returned(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    for i in range(3):
        await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol=f"COIN{i}")

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"limit": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_limit_above_the_max_is_rejected(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"limit": 501},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422


async def test_exchange_venue_settlement_currency_and_symbol_filter_independently(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="BTCUSDT")
    await _seed(pg_session_factory, pool=("binance", "usdt-m", "USDT"), symbol="ETHUSDT")

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"exchange": "bybit"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["BTCUSDT"]


@pytest.mark.parametrize("queried", ["STXUSDT", "STXUSDT.P", "stxusdt.p"])
async def test_the_symbol_filter_finds_a_market_under_any_of_its_spellings(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
    queried: str,
) -> None:
    """The scan stores the market key (``STXUSDT``); an operator reading a
    TradingView alert types ``STXUSDT.P``. Both name one market, so both find
    the row."""
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="STXUSDT")
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="ETHUSDT")

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"symbol": queried},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["STXUSDT"]


# --------------------------------------------------------------------------
# Seeding for the removed booking routes' pins (below). The routes
# (``GET /reconciliation/bookings``, ``POST .../approve``, ``POST .../reject``)
# were Unit 7's admin endpoints; owner decision 66 Q1 removed them.
# --------------------------------------------------------------------------


def _fill(**overrides: object) -> ProposedFillSnapshot:
    defaults: dict[str, object] = {
        "exchange_fill_id": "1001",
        "exchange_order_id": "5001",
        "side": "SELL",
        "quantity": Decimal("0.5"),
        "price": Decimal("142.37"),
        "fee": Decimal("0.03913"),
        "fee_currency": "USDT",
        "filled_at": NOW,
    }
    defaults.update(overrides)
    return ProposedFillSnapshot(**defaults)  # type: ignore[arg-type]


async def _seed_bookable_discrepancy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pool: tuple[str, str, str] = _BOOKING_POOL,
    symbol: str = "STXUSDT.P",
    venue_net_base: Decimal = Decimal("0"),
    ledger_net_base: Decimal = Decimal("0.5"),
) -> tuple[UUID, UUID, UUID]:
    """Seeds a strategy + signal + FILLED reservation (the allocation) and a
    CONFIRMED, single-allocation discrepancy an approval can freshness-check
    against. Returns ``(discrepancy_id, strategy_id, allocation_id)``."""
    strategy_id, signal_id, allocation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(
        session_factory,
        strategy_id=strategy_id,
        exchange=pool[0],
        venue=pool[1],
        settlement_currency=pool[2],
    )
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=pool[0],
        venue=pool[1],
        settlement_currency=pool[2],
        amount=Decimal("100"),
        status="FILLED",
    )
    scan_id = uuid4()
    async with session_factory() as session:
        await SqlAlchemyDiscrepancyRepository(session).upsert_open(
            pool,
            symbol,
            _observation(
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                venue_net_base=venue_net_base,
                ledger_net_base=ledger_net_base,
            ),
            [allocation_id],
            consecutive_scans=2,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=scan_id,
            at=NOW,
        )
        await session.commit()
    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            open_only=True
        )
    discrepancy_id = next(record.id for record in records if record.symbol == symbol)
    return discrepancy_id, strategy_id, allocation_id


async def _seed_pending_proposal(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    discrepancy_id: UUID,
    strategy_id: UUID,
    allocation_id: UUID,
    pool: tuple[str, str, str] = _BOOKING_POOL,
    symbol: str = "STXUSDT.P",
    quantity: Decimal = Decimal("0.5"),
    venue_net_base: Decimal = Decimal("0"),
    ledger_net_base: Decimal = Decimal("0.5"),
    expires_at: datetime | None = None,
    fills: list[ProposedFillSnapshot] | None = None,
) -> UUID:
    proposal = NewBookingProposal(
        discrepancy_id=discrepancy_id,
        exchange=pool[0],
        venue=pool[1],
        settlement_currency=pool[2],
        symbol=symbol,
        kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        side="SELL",
        quantity=quantity,
        observed_venue_net_base=venue_net_base,
        observed_ledger_net_base=ledger_net_base,
        observed_allocation_ids=[allocation_id],
        fills=fills if fills is not None else [_fill()],
        client_order_id=f"vnu:bybit:{uuid4()}",
        expires_at=(
            expires_at if expires_at is not None else datetime.now(UTC) + timedelta(hours=24)
        ),
        prepared_by_job_id=uuid4(),
    )
    async with session_factory() as session:
        record = await SqlAlchemyBookingProposalRepository(session).insert(proposal)
        await session.commit()
    assert record is not None
    return record.id


# --- The booking routes are removed (cd.1.32; owner decision 66 Q1; R18) ------


async def _a_pending_proposal(session_factory: async_sessionmaker[AsyncSession]) -> UUID:
    discrepancy_id, strategy_id, allocation_id = await _seed_bookable_discrepancy(
        session_factory
    )
    return await _seed_pending_proposal(
        session_factory,
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
    )


async def _state_of(session_factory: async_sessionmaker[AsyncSession], proposal_id: UUID) -> str:
    async with session_factory() as session:
        return (
            await SqlAlchemyBookingProposalRepository(session).get_for_update(proposal_id)
        ).state


async def test_the_bookings_list_route_is_gone(authenticated_client: AsyncClient) -> None:
    response = await authenticated_client.get(
        "/reconciliation/bookings", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code in (404, 405)


async def test_the_approve_route_is_gone_and_the_proposal_stays_pending(
    pg_session_factory: async_sessionmaker[AsyncSession], authenticated_client: AsyncClient
) -> None:
    proposal_id = await _a_pending_proposal(pg_session_factory)

    response = await authenticated_client.post(
        f"/reconciliation/bookings/{proposal_id}/approve",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code in (404, 405)
    assert await _state_of(pg_session_factory, proposal_id) == "PENDING"


async def test_the_reject_route_is_gone_and_the_proposal_stays_pending(
    pg_session_factory: async_sessionmaker[AsyncSession], authenticated_client: AsyncClient
) -> None:
    proposal_id = await _a_pending_proposal(pg_session_factory)

    response = await authenticated_client.post(
        f"/reconciliation/bookings/{proposal_id}/reject",
        json={"reason": "duplicate"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code in (404, 405)
    assert await _state_of(pg_session_factory, proposal_id) == "PENDING"


def test_the_router_module_imports_neither_approve_nor_reject_booking() -> None:
    from strategy_manager.reconciliation.infrastructure import router as router_module

    assert not hasattr(router_module, "ApproveBooking")
    assert not hasattr(router_module, "RejectBooking")


def test_reject_booking_does_not_exist() -> None:
    from pathlib import Path

    import strategy_manager.reconciliation.application as application

    assert not (Path(application.__path__[0]) / "reject_booking.py").exists()
