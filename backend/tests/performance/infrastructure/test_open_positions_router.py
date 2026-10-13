"""The open-positions route, field by field (design addendum "open positions",
sections F and L, T8; spec admin-api "The Open Positions Route Answers For The
Whole System" and the five requirements after it; tasks.md op.1.23).

The route is built here over FAKES of its three sources and of the snapshot
session (the database is not what these tests are about: the wire is). The
snapshot, the statements and the invariant are pinned on real PostgreSQL in
``test_open_positions_snapshot``, ``test_open_positions_matches_guard`` and
``test_open_positions_statement_counts``.

Every body is compared WHOLE with ``==``: a field that is added, renamed, omitted
or served as a number is a failed assertion, never a ``KeyError``.

Symbols cross the boundary in different spellings: the guard's element spells a
market ``STXUSDT / STXUSDT.P``, the ledger's groups ``STXUSDT.P``, the route
serves the market key ``STXUSDT``.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import SubmittedOrder
from strategy_manager.performance.domain.open_position import DiscrepancyRow, PoolLabel
from strategy_manager.performance.infrastructure import open_positions_router
from strategy_manager.performance.infrastructure.open_positions_router import (
    get_clock,
    get_disagreement_source,
    get_facts_source,
    get_open_state_source,
    get_snapshot_session,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.performance.fakes import (
    FakeDisagreementSource,
    FakeFactsSource,
    FakeOpenStateReader,
    FixedClock,
)
from tests.performance.open_state_cases import (
    POOL,
    T0,
    fill_aggregate,
    in_flight_element,
    open_element,
    position_facts,
    submitted_order,
)

TOKEN = "adm1n-t0ken"
NOW = datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC)
PIONEX_BTC = PoolLabel("pionex", "coin-m", "BTC")
URL = "/api/positions/open"

POSITION_KEYS = {
    "allocation_id", "strategy_id", "strategy_name", "strategy_archived", "pool", "currency",
    "markets", "origin", "figures_missing", "side", "base_currency", "size", "opened_size",
    "entry_price", "opened_at", "fill_count", "fees", "other_fees", "margin_granted",
    "leverage", "reservation_status", "venue_disagreement",
}  # fmt: skip
ORDER_KEYS = {
    "attempt_id", "strategy_id", "strategy_archived", "strategy_name", "pool", "market",
    "action", "origin", "submitted_at",
}  # fmt: skip
POOL_BODY = {"exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT"}


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _app(
    state: FakeOpenStateReader,
    facts: FakeFactsSource | None = None,
    disagreements: FakeDisagreementSource | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(open_positions_router.router, prefix="/api")

    async def _no_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_snapshot_session] = _no_session
    app.dependency_overrides[get_open_state_source] = lambda: state
    app.dependency_overrides[get_facts_source] = lambda: facts or FakeFactsSource()
    app.dependency_overrides[get_disagreement_source] = (
        lambda: disagreements or FakeDisagreementSource()
    )
    app.dependency_overrides[get_clock] = lambda: FixedClock(NOW)
    return app


async def _get(app: FastAPI, url: str = URL, *, headers: dict[str, str] | None = None) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url, headers=_auth() if headers is None else headers)


async def _body(app: FastAPI, url: str = URL) -> dict[str, Any]:
    response = await _get(app, url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _elements(body: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """The elements of ``body[key]``; a list of anything else is a failed
    ASSERTION (the body is wrong), not a ``TypeError``."""
    items = body[key]
    assert all(isinstance(item, dict) for item in items), (
        f"{key} must hold element objects; it holds {items!r}"
    )
    return list(items)


def _field(body: dict[str, Any], key: str, field: str) -> list[Any]:
    return [element[field] for element in _elements(body, key)]


# --- the body of a live futures position, field by field ---------------------------


async def test_a_live_futures_position_is_served_field_by_field() -> None:
    allocation, strategy = uuid4(), uuid4()
    element = open_element(
        rehearsal=False, live=True, allocation_id=allocation, name="Alpha", symbol="STXUSDT.P"
    )
    facts = FakeFactsSource(
        {
            allocation: position_facts(
                allocation,
                strategy,
                (
                    fill_aggregate(
                        allocation, strategy, quantity="100", price="0.45", fee="0.0000001"
                    ),
                ),
                margin="20",
                leverage="2.00000000",
            )
        }
    )

    body = await _body(_app(FakeOpenStateReader([element]), facts))

    assert body == {
        "as_of": "2026-10-12T10:00:00Z",
        "positions": [
            {
                "allocation_id": str(allocation),
                "strategy_id": str(strategy),
                "strategy_name": "Alpha",
                "strategy_archived": False,
                "pool": POOL_BODY,
                "currency": "USDT",
                "markets": ["STXUSDT"],
                "origin": "live",
                "figures_missing": None,
                "side": "LONG",
                "base_currency": "STX",
                "size": "100",
                "opened_size": "100",
                "entry_price": "0.450000000000000000",
                "opened_at": "2026-10-12T09:00:00Z",
                "fill_count": 1,
                "fees": "0.0000001",
                "other_fees": [],
                "margin_granted": "20",
                "leverage": "2.00000000",
                "reservation_status": "FILLED",
                "venue_disagreement": None,
            }
        ],
        "orders": [],
    }


async def test_no_money_or_size_is_a_json_number_and_none_has_an_exponent() -> None:
    allocation, strategy = uuid4(), uuid4()
    facts = FakeFactsSource(
        {
            allocation: position_facts(
                allocation,
                strategy,
                (
                    fill_aggregate(
                        allocation, strategy, quantity="0.0000001", price="3", fee="0.0000001"
                    ),
                    fill_aggregate(
                        allocation, strategy, quantity="1", price="2", fee="0.5",
                        fee_currency="stx", symbol="STXUSDT.P",
                    ),
                ),
                margin="1E+2",
                leverage="1E+1",
            )
        }
    )
    state = FakeOpenStateReader(
        [open_element(rehearsal=False, live=True, allocation_id=allocation, name="Alpha")]
    )

    response = await _get(_app(state, facts))

    assert response.status_code == 200
    position = _elements(response.json(), "positions")[0]
    for field in ("size", "opened_size", "entry_price", "fees", "margin_granted", "leverage"):
        value = position[field]
        assert isinstance(value, str), f"{field} is a {type(value).__name__}, not a string"
        assert "e" not in value.lower(), f"{field} is written with an exponent: {value}"
    assert position["margin_granted"] == "100"
    assert position["leverage"] == "10"
    assert all(isinstance(fee["amount"], str) for fee in position["other_fees"])


async def test_the_six_fields_nothing_draws_are_not_served() -> None:
    allocation, strategy, attempt = uuid4(), uuid4(), uuid4()
    discrepancy = DiscrepancyRow(
        discrepancy_id=uuid4(), pool=POOL, symbol="STXUSDT", status="CONFIRMED",
        venue_net_base=Decimal("0"), ledger_net_base=Decimal("1"),
        open_allocation_ids=(allocation,), last_observed_at=T0, resolved_at=None,
    )  # fmt: skip
    facts = FakeFactsSource(
        {allocation: position_facts(allocation, strategy, (fill_aggregate(allocation, strategy),))},
        [submitted_order(attempt, strategy_id=strategy)],
    )
    state = FakeOpenStateReader(
        [open_element(rehearsal=False, live=True, allocation_id=allocation)],
        [in_flight_element(rehearsal=False, attempt_id=attempt)],
    )

    body = await _body(_app(state, facts, FakeDisagreementSource([discrepancy])))

    position, order = _elements(body, "positions")[0], _elements(body, "orders")[0]
    assert set(position) == POSITION_KEYS
    assert set(order) == ORDER_KEYS
    assert position["venue_disagreement"] is not None
    assert set(position["venue_disagreement"]) == {
        "discrepancy_id", "venue_net_base", "ledger_net_base", "allocation_count",
        "last_observed_at",
    }  # fmt: skip
    for unread in ("last_fill_at",):
        assert unread not in position
    for unread in ("allocation_id", "side", "margin_reserved"):
        assert unread not in order


# --- a position or an order the facts cannot decorate keeps its row -----------------


async def test_a_position_with_no_facts_writes_its_nullable_fields_as_json_null() -> None:
    allocation = uuid4()
    element = open_element(
        rehearsal=True,
        live=False,
        allocation_id=allocation,
        name="Gamma",
        symbol="STXUSDT / STXUSDT.P",
    )

    body = await _body(_app(FakeOpenStateReader([element])))

    assert body["positions"] == [
        {
            "allocation_id": str(allocation),
            "strategy_id": None,
            "strategy_name": "Gamma",
            "strategy_archived": None,
            "pool": POOL_BODY,
            "currency": "USDT",
            "markets": ["STXUSDT"],
            "origin": "rehearsal",
            "figures_missing": "NO_FACTS",
            "side": None,
            "base_currency": None,
            "size": None,
            "opened_size": None,
            "entry_price": None,
            "opened_at": None,
            "fill_count": 0,
            "fees": None,
            "other_fees": [],
            "margin_granted": None,
            "leverage": None,
            "reservation_status": None,
            "venue_disagreement": None,
        }
    ]


async def test_an_order_the_facts_cannot_decorate_is_served_with_the_readers_own_values() -> None:
    attempt = uuid4()
    element = in_flight_element(
        rehearsal=False, attempt_id=attempt, name="Beta", symbol="ETHUSDT.P"
    )

    body = await _body(_app(FakeOpenStateReader(in_flight=[element])))

    assert body["orders"] == [
        {
            "attempt_id": str(attempt),
            "strategy_id": None,
            "strategy_archived": None,
            "strategy_name": "Beta",
            "pool": POOL_BODY,
            "market": "ETHUSDT",
            "action": None,
            "origin": "live",
            "submitted_at": None,
        }
    ]


async def test_a_decorated_order_carries_its_action_strategy_and_time() -> None:
    attempt, strategy = uuid4(), uuid4()
    element = in_flight_element(rehearsal=True, attempt_id=attempt, symbol="ETHUSDT.P")
    row = submitted_order(
        attempt, opening=False, strategy_id=strategy, name="Beta", archived=True,
        created_at=T0 + timedelta(minutes=5),
    )  # fmt: skip

    app = _app(FakeOpenStateReader(in_flight=[element]), FakeFactsSource(submitted=[row]))

    body = await _body(app)

    assert body["orders"] == [
        {
            "attempt_id": str(attempt),
            "strategy_id": str(strategy),
            "strategy_archived": True,
            "strategy_name": "Beta",
            "pool": POOL_BODY,
            "market": "ETHUSDT",
            "action": "CLOSE",
            "origin": "rehearsal",
            "submitted_at": "2026-10-12T09:05:00Z",
        }
    ]


async def test_an_attempt_with_no_order_id_and_no_parent_is_served_as_unknown() -> None:
    attempt = uuid4()
    row = submitted_order(
        attempt, order_id=None, strategy_id=None, name=None, archived=None,
        reservation_pool=None, symbol="STXUSDT.P",
    )  # fmt: skip

    body = await _body(_app(FakeOpenStateReader(), FakeFactsSource(submitted=[row])))

    assert body["orders"] == [
        {
            "attempt_id": str(attempt),
            "strategy_id": None,
            "strategy_archived": None,
            "strategy_name": None,
            "pool": POOL_BODY,
            "market": "STXUSDT",
            "action": "OPEN",
            "origin": "unknown",
            "submitted_at": "2026-10-12T09:00:00Z",
        }
    ]


# --- the mark -------------------------------------------------------------------------


async def test_a_position_the_venue_disagrees_on_carries_the_finding() -> None:
    allocation, strategy, other = uuid4(), uuid4(), uuid4()
    discrepancy_id = uuid4()
    row = DiscrepancyRow(
        discrepancy_id=discrepancy_id, pool=POOL, symbol="STXUSDT", status="CONFIRMED",
        venue_net_base=Decimal("0.500000000000000000"), ledger_net_base=Decimal("12.5"),
        open_allocation_ids=(allocation, other), last_observed_at=T0, resolved_at=None,
    )  # fmt: skip
    facts = FakeFactsSource(
        {allocation: position_facts(allocation, strategy, (fill_aggregate(allocation, strategy),))}
    )
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    state = FakeOpenStateReader([element])

    body = await _body(_app(state, facts, FakeDisagreementSource([row])))

    assert _field(body, "positions", "venue_disagreement") == [{
        "discrepancy_id": str(discrepancy_id),
        "venue_net_base": "0.500000000000000000",
        "ledger_net_base": "12.5",
        "allocation_count": 2,
        "last_observed_at": "2026-10-12T09:00:00Z",
    }]


# --- several pools, no narrowing ------------------------------------------------------


async def test_two_pools_of_two_exchanges_are_one_answer_each_with_its_own_pool_and_currency() -> (
    None
):
    bybit, pionex = uuid4(), uuid4()
    state = FakeOpenStateReader(
        [
            open_element(rehearsal=False, live=True, allocation_id=bybit, name="Alpha"),
            open_element(
                rehearsal=False, live=True, allocation_id=pionex, name="Beta",
                exchange="pionex", venue="coin-m", settlement_currency="BTC", symbol="ETH_BTC",
            ),
        ]
    )  # fmt: skip

    body = await _body(_app(state))

    pools = {
        p["allocation_id"]: (p["pool"], p["currency"]) for p in _elements(body, "positions")
    }
    assert pools == {
        str(bybit): (POOL_BODY, "USDT"),
        str(pionex): (
            {"exchange": "pionex", "venue": "coin-m", "settlement_currency": "BTC"},
            "BTC",
        ),
    }


@pytest.mark.parametrize(
    "query",
    ["?exchange=pionex", "?strategy_id=" + str(uuid4()), "?pool=bybit&limit=1&offset=5"],
)
async def test_no_parameter_narrows_the_answer(query: str) -> None:
    state = FakeOpenStateReader(
        [
            open_element(rehearsal=False, live=True, name="Alpha"),
            open_element(rehearsal=True, live=False, name="Beta", exchange="pionex"),
        ],
        [in_flight_element(rehearsal=False)],
    )
    app = _app(state)

    plain = await _body(app)
    queried = await _body(app, URL + query)

    assert len(plain["positions"]) == 2 and len(plain["orders"]) == 1
    assert queried == plain


async def test_a_position_of_an_archived_strategy_is_served() -> None:
    allocation, strategy = uuid4(), uuid4()
    facts = FakeFactsSource(
        {
            allocation: position_facts(
                allocation, strategy, (fill_aggregate(allocation, strategy),), archived=True
            )
        }
    )
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    state = FakeOpenStateReader([element])

    body = await _body(_app(state, facts))

    assert _field(body, "positions", "strategy_archived") == [True]


# --- order of the lists ---------------------------------------------------------------


def _ids(*numbers: int) -> list[UUID]:
    return [UUID(int=n) for n in numbers]


async def test_positions_are_sorted_by_strategy_name_pool_market_and_allocation_id() -> None:
    a1, a2, b_eth, b_btc, same_low, same_high = _ids(1, 2, 3, 4, 5, 6)
    elements = [
        open_element(rehearsal=False, live=True, allocation_id=same_high, name="Beta",
                     symbol="ETHUSDT.P"),
        open_element(rehearsal=False, live=True, allocation_id=b_eth, name="Beta",
                     symbol="SOLUSDT.P"),
        open_element(rehearsal=False, live=True, allocation_id=a2, name="Alpha",
                     exchange="pionex", venue="coin-m", settlement_currency="BTC",
                     symbol="ETH_BTC"),
        open_element(rehearsal=False, live=True, allocation_id=b_btc, name="Beta",
                     symbol="BTCUSDT.P"),
        open_element(rehearsal=False, live=True, allocation_id=a1, name="Alpha",
                     symbol="SOLUSDT.P"),
        open_element(rehearsal=False, live=True, allocation_id=same_low, name="Beta",
                     symbol="ETHUSDT.P"),
    ]  # fmt: skip

    forward = await _body(_app(FakeOpenStateReader(elements)))
    backward = await _body(_app(FakeOpenStateReader(list(reversed(elements)))))

    # Alpha: bybit before pionex. Beta (bybit/usdt-m/USDT): BTC, ETH (two, by id), SOL.
    expected = [str(i) for i in (a1, a2, b_btc, same_low, same_high, b_eth)]
    assert _field(forward, "positions", "allocation_id") == expected
    assert _field(backward, "positions", "allocation_id") == expected


async def test_orders_sort_by_submitted_at_then_attempt_id_with_an_unknown_time_last() -> None:
    early, tie_a, tie_b, late, null_a, null_b = _ids(11, 12, 13, 14, 15, 16)
    in_flight = [in_flight_element(rehearsal=False, attempt_id=i) for i in (
        null_b, late, tie_b, null_a, tie_a, early)]  # fmt: skip
    rows = [
        submitted_order(early, created_at=T0),
        submitted_order(tie_a, created_at=T0 + timedelta(minutes=30)),
        submitted_order(tie_b, created_at=T0 + timedelta(minutes=30)),
        submitted_order(late, created_at=T0 + timedelta(hours=1)),
    ]
    app = _app(FakeOpenStateReader(in_flight=in_flight), FakeFactsSource(submitted=rows))

    body = await _body(app)

    assert _field(body, "orders", "attempt_id") == [
        str(i) for i in (early, tie_a, tie_b, late, null_a, null_b)
    ]


# --- 401 and 500 ----------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
async def test_the_route_refuses_a_request_without_the_token(headers: dict[str, str]) -> None:
    response = await _get(_app(FakeOpenStateReader()), headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": UNAUTHORIZED_DETAIL}


class _FailingState:
    async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
        raise RuntimeError("the database is down")

    async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
        raise RuntimeError("the database is down")


async def test_a_failed_read_is_a_500_and_never_an_empty_list() -> None:
    app = _app(FakeOpenStateReader())
    app.dependency_overrides[get_open_state_source] = lambda: _FailingState()

    response = await _get(app)

    assert response.status_code == 500
    assert "positions" not in response.text


async def test_a_failed_facts_read_is_a_500_too() -> None:
    class _FailingFacts(FakeFactsSource):
        async def submitted_orders(self) -> Sequence[SubmittedOrder]:
            raise RuntimeError("the database is down")

    app = _app(FakeOpenStateReader(), _FailingFacts())

    response = await _get(app)

    assert response.status_code == 500
    assert "positions" not in response.text


async def test_as_of_is_the_servers_clock() -> None:
    body = await _body(_app(FakeOpenStateReader()))

    assert body == {"as_of": "2026-10-12T10:00:00Z", "positions": [], "orders": []}

