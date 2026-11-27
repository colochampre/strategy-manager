"""``GET /api/notifications`` and ``GET /api/notifications/unseen`` [DB]
(panel-redesign RD.5a, the panel's Notifications feed).

Mounted through ``create_app()`` over real PostgreSQL. Operations are written
through ``RecordFill`` (the production write path); the trades read, the open
positions read, the safety events, the deliveries and the reconciliation's
confirmed read are the real ones, so what is under test is the wire.

**Binding testing lesson.** A symbol has three spellings. Every row here is
written in the spelling of ITS side of a boundary (``STXUSDT.P`` on a signal, a
safety event and an opening fill; ``STXUSDT`` on a closing fill) and the feed
answers the venue's market key, ``STXUSDT``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.main import create_app
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import ADMIN_HEADERS, FORGED_HEADERS, OTHER_HEADERS, act_as
from tests.owner import OWNER_ID, ensure_delivery, seed_other_user
from tests.performance.infrastructure.conftest import seed_signal
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    PIONEX,
    _fill,
    _record,
    _seed_allocation,
)
from tests.performance.infrastructure.test_my_trades_router import _safety_event
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    _json,
    _signed_in,
    _strategy,
)
from tests.reconciliation.infrastructure.test_confirmed_router import _discrepancy

pytestmark = pytest.mark.integration

URL = "/api/notifications"
UNSEEN_URL = "/api/notifications/unseen"
T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
SECRET = "outcome detail with ids 3f2c and a user e-mail"
NOTICE_REASONS = (
    "EXCHANGE_HAS_NO_KEY",
    "EXCHANGE_KEY_READ_ONLY",
    "MARGIN_NOT_ISOLATED",
    "LEVERAGE_CONFLICT",
    "LEVERAGE_NOT_APPLIED",
)
ITEM_KEYS = {
    "id", "kind", "event", "occurred_at", "reason", "strategy_id", "strategy_name", "exchange",
    "venue", "pair", "side", "rehearsal", "currency", "entry_price", "exit_price", "pnl",
    "leverage", "close_cause", "detail",
}  # fmt: skip


def _at(hours: int = 0, minutes: int = 0) -> datetime:
    return T0 + timedelta(hours=hours, minutes=minutes)


def _z(instant: datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


@asynccontextmanager
async def _api(
    factory: async_sessionmaker[AsyncSession], *, dry_run: bool = False
) -> AsyncIterator[AsyncClient]:
    """The app as the fixtures' owner, with the DRY_RUN brake as ``dry_run`` says.
    The settings are a COPY handed to the dependency: the shared ones are never
    changed."""
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    def _settings() -> Any:
        return get_settings().model_copy(
            update={"dry_run": dry_run, "reconciliation_auto_booking_grace_seconds": 300}
        )

    app.dependency_overrides[shared_db.get_session] = _session
    app.dependency_overrides[get_settings] = _settings
    act_as(app, OWNER_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with _api(pg_session_factory) as api:
        yield api


async def _get(
    client: AsyncClient, *, headers: dict[str, str] | None = None, **params: Any
) -> dict[str, Any]:
    response = await client.get(
        URL, headers=ADMIN_HEADERS if headers is None else headers, params=params
    )
    assert response.status_code == 200, response.text
    return dict(_json(response))


async def _unseen(client: AsyncClient, since: datetime, **kwargs: Any) -> list[str]:
    response = await client.get(
        UNSEEN_URL, headers=kwargs.get("headers", ADMIN_HEADERS), params={"since": _z(since)}
    )
    assert response.status_code == 200, response.text
    return list(response.json()["kinds"])


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["items"]]


async def _everything(client: AsyncClient, limit: int, **params: Any) -> list[dict[str, Any]]:
    """Every item, page by page, following ``next_cursor`` until it is null."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100):
        extra: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
        body = await _get(client, limit=limit, **params, **extra)
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("the pages never ended")


# --- seeding ----------------------------------------------------------------------------


async def _operation(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    opened_at: datetime,
    *,
    closed_at: datetime | None = None,
    pool: PoolKey = BYBIT,
    opened_by: str = "BUY",
    entry: str = "100",
    exit_: str = "110",
    rehearsal: bool = False,
    leverage: str | None = None,
    user_id: UUID = OWNER_ID,
) -> UUID:
    """One allocation of ``strategy_id``, opened at ``opened_at`` as ``STXUSDT.P``
    and, when ``closed_at`` is given, closed then as ``STXUSDT``."""
    _, allocation_id, attempt_id = await _seed_allocation(
        factory, pool=pool, strategy_id=strategy_id, user_id=user_id
    )

    def fill_id() -> str | None:
        return f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}" if rehearsal else None

    closing = "SELL" if opened_by == "BUY" else "BUY"
    fills = [
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side=opened_by,
            quantity="1",
            price=entry,
            symbol="STXUSDT.P",
            filled_at=opened_at,
            fill_id=fill_id(),
            pool=pool,
            user_id=user_id,
        )
    ]
    if closed_at is not None:
        fills.append(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side=closing,
                quantity="1",
                price=exit_,
                symbol="STXUSDT",
                filled_at=closed_at,
                fill_id=fill_id(),
                pool=pool,
                user_id=user_id,
            )
        )
    await _record(factory, *fills)
    if leverage is not None:
        async with factory() as session:
            await session.execute(
                text("UPDATE execution_attempts SET leverage = :v WHERE reservation_id = :id"),
                {"v": leverage, "id": allocation_id},
            )
            await session.commit()
    return allocation_id


async def _delivery(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    *,
    reason: str,
    decided_at: datetime,
    status: str = "REJECTED",
    user_id: UUID = OWNER_ID,
    symbol: str = "STXUSDT.P",
    detail: str | None = None,
    delivery_id: UUID | None = None,
) -> UUID:
    """A signal of ``strategy_id`` on ``symbol`` and its delivery to ``user_id``,
    decided as ``status`` with ``reason``."""
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    async with factory() as session:
        await session.execute(
            text("UPDATE signals SET symbol = :symbol WHERE id = :id"),
            {"symbol": symbol, "id": signal_id},
        )
        made = await ensure_delivery(
            session,
            signal_id=signal_id,
            strategy_id=strategy_id,
            user_id=user_id,
            delivery_id=delivery_id,
        )
        await session.execute(
            text(
                "UPDATE signal_deliveries SET status = :status, outcome_reason = :reason, "
                "outcome_detail = :detail, decided_at = :decided_at WHERE id = :id"
            ),
            {
                "status": status,
                "reason": reason,
                "detail": detail if detail is not None else SECRET,
                "decided_at": decided_at,
                "id": made,
            },
        )
        await session.commit()
    return made


async def _refusal(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    kind: str,
    occurred_at: datetime,
    *,
    user_id: UUID = OWNER_ID,
    detail: dict[str, str] | None = None,
) -> UUID:
    """One ``OPENING_REFUSED_*`` safety event, written as production does: from a
    delivery, with no allocation."""
    delivery_id = await _delivery(
        factory, strategy_id, reason="LEVERAGE_ABOVE_STOP_CAP", decided_at=occurred_at,
        user_id=user_id,
    )  # fmt: skip
    event_id = uuid4()
    async with factory() as session:
        session.add(
            SafetyEventRow(
                id=event_id,
                user_id=user_id,
                kind=kind,
                strategy_id=strategy_id,
                allocation_id=None,
                exchange="bybit",
                venue="usdt-m",
                symbol="STXUSDT.P",
                occurred_at=occurred_at,
                detail=detail or {},
                delivery_id=delivery_id,
            )
        )
        await session.commit()
    return event_id


# --- OPENED and CLOSED -----------------------------------------------------------------


async def test_a_closed_operation_gives_a_closed_item_and_an_opened_item(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _operation(
        pg_session_factory, strategy_id, _at(1), closed_at=_at(2), leverage="3"
    )
    common = {
        "kind": "OPERATION",
        "reason": None,
        "strategy_id": str(strategy_id),
        "strategy_name": f"strategy-{strategy_id}",
        "exchange": "bybit",
        "venue": "usdt-m",
        "pair": "STXUSDT",
        "side": "LONG",
        "rehearsal": False,
        "currency": "USDT",
        "detail": {},
    }

    body = await _get(client)

    assert body == {
        "items": [
            {
                **common,
                "id": f"closed:{allocation_id}",
                "event": "CLOSED",
                "occurred_at": _z(_at(2)),
                "entry_price": None,
                "exit_price": "110.000000000000000000",
                "pnl": "10.000000000000000000",
                "leverage": None,
                "close_cause": "SIGNAL",
            },
            {
                **common,
                "id": f"opened:{allocation_id}",
                "event": "OPENED",
                "occurred_at": _z(_at(1)),
                "entry_price": "100.000000000000000000",
                "exit_price": None,
                "pnl": None,
                "leverage": "3.00000000",
                "close_cause": None,
            },
        ],
        "next_cursor": None,
    }


async def test_an_open_operation_gives_an_opened_item_only(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _operation(
        pg_session_factory, strategy_id, _at(1), opened_by="SELL", entry="50", leverage="2"
    )

    body = await _get(client)

    (item,) = body["items"]
    assert set(item) == ITEM_KEYS
    assert item["id"] == f"opened:{allocation_id}"
    assert (item["kind"], item["event"], item["occurred_at"]) == ("OPERATION", "OPENED", _z(_at(1)))
    assert (item["side"], item["pair"], item["currency"]) == ("SHORT", "STXUSDT", "USDT")
    assert item["entry_price"] == "50.000000000000000000"
    assert item["leverage"] == "2.00000000"
    assert (item["exit_price"], item["pnl"], item["close_cause"]) == (None, None, None)
    assert item["strategy_name"] == f"strategy-{strategy_id}"
    assert body["next_cursor"] is None


async def test_the_leverage_is_null_when_the_opening_recorded_none(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, PIONEX)
    await _operation(pg_session_factory, strategy_id, _at(1), closed_at=_at(2), pool=PIONEX)

    body = await _get(client)

    opened = next(item for item in body["items"] if item["event"] == "OPENED")
    assert opened["leverage"] is None
    assert (opened["exchange"], opened["venue"]) == ("pionex", "spot")


@pytest.mark.parametrize("closed", [False, True])
async def test_a_rehearsal_operation_is_flagged_and_a_live_one_is_not(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession], closed: bool
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    live = await _operation(
        pg_session_factory, strategy_id, _at(1), closed_at=_at(2) if closed else None
    )
    rehearsal = await _operation(
        pg_session_factory, strategy_id, _at(3), closed_at=_at(4) if closed else None,
        rehearsal=True,
    )  # fmt: skip

    body = await _get(client)

    flags = {item["id"]: item["rehearsal"] for item in body["items"]}
    assert flags[f"opened:{live}"] is False
    assert flags[f"opened:{rehearsal}"] is True
    if closed:
        assert flags[f"closed:{live}"] is False
        assert flags[f"closed:{rehearsal}"] is True


@pytest.mark.parametrize(
    ("close_kind", "kind"),
    [
        (None, "OPERATION"),
        ("MANUAL_CLOSE", "OPERATION"),
        ("STOP_FIRED", "SAFETY"),
        ("STOP_FAILED_CLOSED", "SAFETY"),
        ("STRATEGY_STOPPED_CLOSED", "SAFETY"),
    ],
)
async def test_a_close_is_an_operation_or_a_safety_item_by_its_cause(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    close_kind: str | None,
    kind: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    allocation_id = await _operation(pg_session_factory, strategy_id, _at(1), closed_at=_at(2))
    if close_kind is not None:
        await _safety_event(pg_session_factory, allocation_id, strategy_id, close_kind)

    body = await _get(client)

    # One close, one item: the safety event that explains it is not listed again.
    assert _ids(body) == [f"closed:{allocation_id}", f"opened:{allocation_id}"]
    closed, opened = body["items"]
    assert (closed["kind"], closed["close_cause"]) == (kind, close_kind or "SIGNAL")
    assert opened["kind"] == "OPERATION"


# --- OPENING_REFUSED, from the safety events ---------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "OPENING_REFUSED_LEVERAGE_CAP",
        "OPENING_REFUSED_ACCOUNT_SUSPENDED",
        "OPENING_REFUSED_AUTHOR_SUSPENDED",
    ],
)
async def test_a_refused_opening_event_is_a_safety_item(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession], kind: str
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    detail = {"requested_leverage": "10", "max_leverage": "5", "stop_loss_pct": "19"}
    event_id = await _refusal(pg_session_factory, strategy_id, kind, _at(3), detail=detail)

    body = await _get(client)

    assert body == {
        "items": [
            {
                "id": f"refused:{event_id}",
                "kind": "SAFETY",
                "event": "OPENING_REFUSED",
                "occurred_at": _z(_at(3)),
                "reason": kind,
                "strategy_id": str(strategy_id),
                "strategy_name": f"strategy-{strategy_id}",
                "exchange": "bybit",
                "venue": "usdt-m",
                "pair": "STXUSDT",
                "side": None,
                "rehearsal": False,
                "currency": None,
                "entry_price": None,
                "exit_price": None,
                "pnl": None,
                "leverage": None,
                "close_cause": None,
                "detail": detail,
            }
        ],
        "next_cursor": None,
    }


# --- OPENING_REFUSED, from the notices ---------------------------------------------------


@pytest.mark.parametrize("reason", NOTICE_REASONS)
async def test_a_rejected_delivery_with_a_fixable_reason_is_a_notice(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession], reason: str
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    delivery_id = await _delivery(
        pg_session_factory, strategy_id, reason=reason, decided_at=_at(5)
    )

    response = await client.get(URL, headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": f"notice:{delivery_id}",
                "kind": "NOTICE",
                "event": "OPENING_REFUSED",
                "occurred_at": _z(_at(5)),
                "reason": reason,
                "strategy_id": str(strategy_id),
                "strategy_name": f"strategy-{strategy_id}",
                "exchange": "bybit",
                "venue": "usdt-m",
                "pair": "STXUSDT",
                "side": None,
                "rehearsal": False,
                "currency": "USDT",
                "entry_price": None,
                "exit_price": None,
                "pnl": None,
                "leverage": None,
                "close_cause": None,
                "detail": {},
            }
        ],
        "next_cursor": None,
    }
    # ``outcome_detail`` is free text with ids: it never leaves the database.
    assert SECRET not in response.text
    assert "outcome_detail" not in response.text


@pytest.mark.parametrize(
    "reason", ["ACCOUNT_SUSPENDED", "LEVERAGE_ABOVE_STOP_CAP", "NO_AVAILABILITY", "SOMETHING_NEW"]
)
async def test_a_rejected_delivery_outside_the_allow_list_is_not_a_notice(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession], reason: str
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _delivery(pg_session_factory, strategy_id, reason=reason, decided_at=_at(5))

    body = await _get(client)

    assert body == {"items": [], "next_cursor": None}


async def test_a_processed_delivery_is_not_a_notice_whatever_its_reason(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _delivery(
        pg_session_factory, strategy_id, reason="EXCHANGE_HAS_NO_KEY", decided_at=_at(5),
        status="PROCESSED",
    )  # fmt: skip

    body = await _get(client)

    assert body == {"items": [], "next_cursor": None}


# --- DISCREPANCY -------------------------------------------------------------------------


async def test_an_admin_gets_the_discrepancies_that_need_the_owner(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    needs = await _discrepancy(
        pg_session_factory, symbol="AAAUSDT.P", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )
    # Still inside the grace the system books it in: nobody has to decide.
    await _discrepancy(
        pg_session_factory, symbol="BBBUSDT", confirmed_ago=timedelta(seconds=10)
    )

    body = await _get(client)

    (item,) = body["items"]
    assert set(item) == ITEM_KEYS
    assert item["id"] == f"discrepancy:{needs}"
    assert (item["kind"], item["event"]) == ("DISCREPANCY", "DISCREPANCY")
    assert item["reason"] == "NO_MATCHING_ALLOCATION"
    assert (item["exchange"], item["venue"], item["currency"]) == ("bybit", "usdt-m", "USDT")
    assert item["pair"] == "AAAUSDT"
    assert (item["strategy_id"], item["strategy_name"], item["rehearsal"]) == (None, None, False)
    assert item["detail"] == {}
    occurred = datetime.fromisoformat(item["occurred_at"])
    assert datetime.now(UTC) - occurred < timedelta(hours=2)


async def test_a_user_who_is_not_the_admin_gets_no_discrepancy_item(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _discrepancy(
        pg_session_factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )

    everything = await _get(client, headers=OTHER_HEADERS)
    only = await client.get(URL, headers=OTHER_HEADERS, params={"kind": "DISCREPANCY"})

    assert everything == {"items": [], "next_cursor": None}
    assert only.status_code == 200
    assert only.json() == {"items": [], "next_cursor": None}


async def test_no_discrepancy_item_while_dry_run_is_on(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _discrepancy(
        pg_session_factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )

    async with _api(pg_session_factory, dry_run=True) as client:
        body = await _get(client)

    assert body == {"items": [], "next_cursor": None}


# --- order and paging --------------------------------------------------------------------


async def test_the_newest_item_comes_first_and_equal_instants_are_told_apart_by_id(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    older = await _delivery(
        pg_session_factory, strategy_id, reason="EXCHANGE_HAS_NO_KEY", decided_at=_at(1)
    )
    tied = [
        await _delivery(
            pg_session_factory, strategy_id, reason="LEVERAGE_CONFLICT", decided_at=_at(2)
        )
        for _ in range(3)
    ]
    newest = await _delivery(
        pg_session_factory, strategy_id, reason="MARGIN_NOT_ISOLATED", decided_at=_at(3)
    )

    body = await _get(client)

    tied_ids = sorted((f"notice:{d}" for d in tied), reverse=True)
    assert _ids(body) == [f"notice:{newest}", *tied_ids, f"notice:{older}"]


async def test_pages_neither_lose_nor_repeat_an_item_tied_at_one_instant(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    made = [
        await _delivery(
            pg_session_factory, strategy_id, reason="LEVERAGE_CONFLICT",
            decided_at=_at(1 if n < 4 else 2),
        )  # fmt: skip
        for n in range(7)
    ]
    whole = await _get(client, limit=100)

    for limit in (1, 2, 3):
        items = await _everything(client, limit)
        assert [item["id"] for item in items] == _ids(whole), limit

    assert sorted(_ids(whole)) == sorted(f"notice:{d}" for d in made)
    first = await _get(client, limit=2)
    assert first["next_cursor"] is not None
    last = await _get(client, limit=7)
    assert last["next_cursor"] is None


async def test_the_default_page_is_thirty(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    for n in range(31):
        await _delivery(
            pg_session_factory, strategy_id, reason="LEVERAGE_CONFLICT", decided_at=_at(n)
        )

    body = await _get(client)

    assert len(body["items"]) == 30
    assert body["next_cursor"] is not None


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"cursor": "not-a-cursor"},
        {"cursor": "e30"},  # base64 of "{}": decodes, and is not a cursor
        {"kind": "EVERYTHING"},
    ],
)
async def test_a_bad_query_is_a_422(client: AsyncClient, params: dict[str, Any]) -> None:
    response = await client.get(URL, headers=ADMIN_HEADERS, params=params)

    assert response.status_code == 422, response.text


# --- the kind filter ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("OPERATION", {"opened_signal", "opened_stop", "closed_signal"}),
        ("SAFETY", {"closed_stop", "refused"}),
        ("NOTICE", {"notice"}),
        ("DISCREPANCY", {"discrepancy"}),
    ],
)
async def test_kind_keeps_the_items_of_that_kind(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    kind: str,
    expected: set[str],
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    by_signal = await _operation(pg_session_factory, strategy_id, _at(1), closed_at=_at(2))
    by_stop = await _operation(pg_session_factory, strategy_id, _at(3), closed_at=_at(4))
    await _safety_event(pg_session_factory, by_stop, strategy_id, "STOP_FIRED")
    refused = await _refusal(
        pg_session_factory, strategy_id, "OPENING_REFUSED_ACCOUNT_SUSPENDED", _at(5)
    )
    notice = await _delivery(
        pg_session_factory, strategy_id, reason="EXCHANGE_KEY_READ_ONLY", decided_at=_at(6)
    )
    discrepancy = await _discrepancy(
        pg_session_factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )
    names = {
        "opened_signal": f"opened:{by_signal}",
        "opened_stop": f"opened:{by_stop}",
        "closed_signal": f"closed:{by_signal}",
        "closed_stop": f"closed:{by_stop}",
        "refused": f"refused:{refused}",
        "notice": f"notice:{notice}",
        "discrepancy": f"discrepancy:{discrepancy}",
    }
    assert set(_ids(await _get(client, limit=100))) == set(names.values())

    body = await _get(client, kind=kind, limit=100)

    assert set(_ids(body)) == {names[name] for name in expected}
    assert {item["kind"] for item in body["items"]} == {kind}


# --- unseen ------------------------------------------------------------------------------


async def test_unseen_lists_the_kinds_after_since_in_priority_order(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _operation(pg_session_factory, strategy_id, _at(10), closed_at=_at(11))
    await _delivery(
        pg_session_factory, strategy_id, reason="LEVERAGE_CONFLICT", decided_at=_at(12)
    )
    await _refusal(pg_session_factory, strategy_id, "OPENING_REFUSED_LEVERAGE_CAP", _at(13))
    await _discrepancy(
        pg_session_factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )

    assert await _unseen(client, _at(0)) == ["SAFETY", "DISCREPANCY", "NOTICE", "OPERATION"]
    assert await _unseen(client, _at(11, 30)) == ["SAFETY", "DISCREPANCY", "NOTICE"]
    assert await _unseen(client, _at(12, 30)) == ["SAFETY", "DISCREPANCY"]
    assert await _unseen(client, datetime.now(UTC) + timedelta(days=1)) == []


async def test_unseen_counts_only_items_strictly_after_since(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    await _operation(pg_session_factory, strategy_id, _at(1))

    assert await _unseen(client, _at(1)) == []
    assert await _unseen(client, _at(1) - timedelta(microseconds=1)) == ["OPERATION"]


async def test_unseen_leaves_the_discrepancy_out_for_a_user_who_is_not_the_admin(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _discrepancy(
        pg_session_factory, symbol="AAAUSDT", kind=DiscrepancyKind.NO_MATCHING_ALLOCATION
    )

    assert await _unseen(client, _at(0), headers=OTHER_HEADERS) == []
    assert await _unseen(client, _at(0)) == ["DISCREPANCY"]


@pytest.mark.parametrize("params", [{}, {"since": "2026-09-21T12:00:00"}, {"since": "soon"}])
async def test_unseen_needs_an_aware_since(client: AsyncClient, params: dict[str, Any]) -> None:
    response = await client.get(UNSEEN_URL, headers=ADMIN_HEADERS, params=params)

    assert response.status_code == 422, response.text


# --- whose rows --------------------------------------------------------------------------


async def test_another_users_rows_never_appear(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    strategy_id = await _strategy(pg_session_factory, BYBIT)
    mine = await _operation(pg_session_factory, strategy_id, _at(1), closed_at=_at(2))
    theirs = await _operation(
        pg_session_factory, strategy_id, _at(3), closed_at=_at(4), user_id=other
    )
    await _safety_event(pg_session_factory, theirs, strategy_id, "STOP_FIRED", user_id=other)
    await _refusal(
        pg_session_factory, strategy_id, "OPENING_REFUSED_LEVERAGE_CAP", _at(5), user_id=other
    )
    await _delivery(
        pg_session_factory, strategy_id, reason="EXCHANGE_HAS_NO_KEY", decided_at=_at(6),
        user_id=other,
    )  # fmt: skip

    body = await _get(client, limit=100)

    assert _ids(body) == [f"closed:{mine}", f"opened:{mine}"]
    assert await _unseen(client, _at(2, 30)) == []


async def test_the_routes_require_a_signed_in_user(client: AsyncClient) -> None:
    for url in (URL, UNSEEN_URL):
        assert (await client.get(url, params={"since": _z(T0)})).status_code == 401
        forged = await client.get(url, headers=FORGED_HEADERS, params={"since": _z(T0)})
        assert forged.status_code == 401
