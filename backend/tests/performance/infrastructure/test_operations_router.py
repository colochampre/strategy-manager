"""API tests for a strategy's operations [DB] (design.md, addendum "a strategy's
operations, listed and opened one by one", sections D, G and H):

- ``GET /api/performance/strategies/{id}/trades`` with its new fields and the
  ``include_rehearsal`` parameter;
- ``GET /api/performance/strategies/{id}/trades/{allocation_id}/fills``.

Mounted through ``create_app()`` over real PostgreSQL on the ORM schema, against
the one ledger of unit 9p.4 (``operations_ledger``). Every fill is written
through ``RecordFill``; the sources, the reads and the derivations are the real
ones, so what is under test is the wire.

**Binding testing lesson.** A symbol has three spellings. The real operations of
the one ledger open as ``STXUSDT.P`` and close as ``STXUSDT``; the rehearsal ones
open as ``STXUSDT_PERP`` and close as ``STXUSDT.P``. The API answers every one of
them as pair ``STXUSDT`` with base currency ``STX``, and the fills route, which
keys on the allocation, answers the fills of both spellings.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.operation import OperationFill
from strategy_manager.performance.infrastructure.performance_router import (
    get_fills_source,
    get_operation_fills_source,
)
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.performance.fakes import FakeFillsSource, FakeOperationFillsSource
from tests.performance.infrastructure.conftest import (
    OPERATIONS_T0,
    OperationsLedger,
    _rehearsal_id,
)
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)
from tests.performance.infrastructure.test_operations_statement_counts import (
    _captured_sql,
)
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    _app,
    _auth,
    _configure_admin_token,
    _json,
    _strategy,
    _walk,
)

pytestmark = pytest.mark.integration

ZERO = "0.000000000000000000"


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(pg_session_factory)), base_url="http://test"
    ) as api:
        yield api


def _trades_url(strategy_id: UUID) -> str:
    return f"/api/performance/strategies/{strategy_id}/trades"


async def _list(
    client: AsyncClient, strategy_id: UUID, **params: Any
) -> dict[str, Any]:
    response = await client.get(_trades_url(strategy_id), headers=_auth(), params=params)
    assert response.status_code == 200, response.text
    return dict(_json(response))


def _ids(page: dict[str, Any]) -> list[str]:
    return [row["allocation_id"] for row in page["trades"]]


def _row(page: dict[str, Any], allocation_id: UUID) -> dict[str, Any]:
    rows = [row for row in page["trades"] if row["allocation_id"] == str(allocation_id)]
    assert len(rows) == 1, f"{allocation_id} is in the page {len(rows)} times"
    return dict(rows[0])


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hours(n: int, minutes: int = 0) -> datetime:
    return OPERATIONS_T0 + timedelta(hours=n, minutes=minutes)


# --- the list: the new fields ----------------------------------------------------------


async def test_a_closed_real_operation_carries_every_new_field(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    """The real LONG of the one ledger: three opening fills of 100 at 0.40, 300 at
    0.44 and 600 at 0.46, sold as 1000 at 0.50, with a fee of 0.1 on each of the
    four fills. The entry price is the quantity-weighted 0.448, not a mean of the
    averages, and the PnL is exactly (exit - entry) x size - fees."""
    ledger = operations_ledger

    page = await _list(client, ledger.strategy_id)

    assert _row(page, ledger.real_long) == {
        "allocation_id": str(ledger.real_long),
        "pair": "STXUSDT",
        "direction": "LONG",
        "opened_at": _iso(_hours(0)),
        "closed_at": _iso(_hours(1)),
        "rehearsal": False,
        "rehearsal_fill_price": None,
        "base_currency": "STX",
        "entry_price": "0.448000000000000000",
        "exit_price": "0.500000000000000000",
        "size": "1000.000000000000000000",
        "fees": "0.400000000000000000",
        "other_fees": [],
        "pnl": "51.600000000000000000",
        "capital_at_open": "1000.000000000000000000",
        "return": "0.0516000000",
        "fees_complete": True,
    }


async def test_a_real_short_enters_on_its_sell_side(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    row = _row(await _list(client, ledger.strategy_id), ledger.real_short)

    assert (row["direction"], row["entry_price"], row["exit_price"], row["size"]) == (
        "SHORT",
        "0.500000000000000000",
        "0.450000000000000000",
        "200.000000000000000000",
    )
    assert (row["fees"], row["pnl"]) == ("0.100000000000000000", "9.900000000000000000")


async def test_a_fee_in_another_currency_is_listed_with_its_own_currency(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Rule 7: a fee in a third currency is never converted. It is listed in its
    own currency, the settlement-currency ``fees`` stay what ``pnl`` subtracts,
    and ``fees_complete`` says the PnL omits it."""
    strategy_id = await _strategy(pg_session_factory)
    _, allocation_id, attempt_id = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id
    )
    await _record(
        pg_session_factory,
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="BUY", quantity="10", price="2", symbol="STXUSDT.P", fee="0.00005",
              fee_currency="BNB", filled_at=_hours(0)),
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="SELL", quantity="10", price="3", symbol="STXUSDT", fee="0.00007",
              fee_currency="bnb", filled_at=_hours(1)),
    )

    row = _row(await _list(client, strategy_id), allocation_id)

    assert row["other_fees"] == [{"currency": "BNB", "amount": "0.000120000000000000"}]
    # No fill was charged in the settlement currency: a sum of nothing is a bare zero.
    assert Decimal(row["fees"]) == 0
    assert row["fees_complete"] is False
    assert row["pnl"] == "10.000000000000000000"


async def test_figures_that_cannot_be_derived_are_null_together_and_the_row_is_served(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """An allocation whose fills name two markets nets to zero and is closed, so
    it is in the totals and stays in the list; its entry price, exit price, size
    and base currency are null TOGETHER, never zero."""
    strategy_id = await _strategy(pg_session_factory)
    _, allocation_id, attempt_id = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id
    )
    await _record(
        pg_session_factory,
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="BUY", quantity="4", price="2", symbol="STXUSDT.P", filled_at=_hours(0)),
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="SELL", quantity="4", price="3", symbol="SOLUSDT", filled_at=_hours(1)),
    )

    row = _row(await _list(client, strategy_id), allocation_id)

    assert [row[k] for k in ("base_currency", "entry_price", "exit_price", "size")] == [None] * 4
    assert (row["pnl"], row["fees"], row["other_fees"]) == ("4.000000000000000000", ZERO, [])


# --- the list: rehearsal rows on request -----------------------------------------------


async def test_the_default_request_holds_no_rehearsal_row_and_every_row_says_rehearsal_false(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    page = await _list(client, ledger.strategy_id)

    assert _ids(page) == [str(a) for a in ledger.real_closed]
    assert [row["rehearsal"] for row in page["trades"]] == [False, False, False]
    assert [row["rehearsal_fill_price"] for row in page["trades"]] == [None, None, None]


async def test_the_opted_in_request_holds_both_kinds_marked_and_the_classification_is_null_exactly_on_a_real_row(  # noqa: E501
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    page = await _list(client, ledger.strategy_id, include_rehearsal="true")

    assert _ids(page) == [
        str(ledger.opened_at_one_closed_at_alert),
        str(ledger.alert_of_one),
        str(ledger.alert_small),
        str(ledger.fixed_one),
        str(ledger.mixed),
        str(ledger.real_short),
        str(ledger.real_long),
    ]
    assert [(row["rehearsal"], row["rehearsal_fill_price"]) for row in page["trades"]] == [
        (True, "FIXED_ONE"),
        (True, "ALERT"),
        (True, "ALERT"),
        (True, "FIXED_ONE"),
        (False, None),
        (False, None),
        (False, None),
    ]
    for row in page["trades"]:
        assert (row["rehearsal"]) == (row["rehearsal_fill_price"] is not None)
        assert (row["pair"], row["base_currency"]) == ("STXUSDT", "STX")


async def test_a_fixed_price_row_is_served_with_entry_one_and_pnl_zero_and_fixed_one(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    page = await _list(client, ledger.strategy_id, include_rehearsal="true")

    one = "1.000000000000000000"
    assert _row(page, ledger.fixed_one) == {
        "allocation_id": str(ledger.fixed_one),
        "pair": "STXUSDT",
        "direction": "LONG",
        "opened_at": _iso(_hours(7)),
        "closed_at": _iso(_hours(7, 30)),
        "rehearsal": True,
        "rehearsal_fill_price": "FIXED_ONE",
        "base_currency": "STX",
        "entry_price": one,
        "exit_price": one,
        "size": "1250.000000000000000000",
        "fees": ZERO,
        "other_fees": [],
        "pnl": ZERO,
        "capital_at_open": "1000.000000000000000000",
        "return": "0.0000000000",
        "fees_complete": True,
    }
    # Opened at 1 and closed at its alert's price: the row that was open when the
    # simulated exchange changed. Its entry is not a price, so it reads FIXED_ONE.
    late = _row(page, ledger.opened_at_one_closed_at_alert)
    assert (late["rehearsal_fill_price"], late["entry_price"], late["exit_price"]) == (
        "FIXED_ONE",
        one,
        "0.451200000000000000",
    )
    assert late["pnl"] == "-54.880000000000000000"


async def test_a_strategy_that_only_ran_in_dry_run_lists_its_operations_while_its_report_shows_zero(  # noqa: E501
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    _, allocation_id, attempt_id = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id
    )
    await _record(
        pg_session_factory,
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="BUY", quantity="3", price="1", symbol="STXUSDT_PERP",
              filled_at=_hours(0), fill_id=_rehearsal_id()),
        _fill(strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
              side="SELL", quantity="3", price="1", symbol="STXUSDT.P",
              filled_at=_hours(1), fill_id=_rehearsal_id()),
    )

    listed = await _list(client, strategy_id, include_rehearsal="true")
    default = await _list(client, strategy_id)
    report = await client.get(f"/api/performance/strategies/{strategy_id}", headers=_auth())

    assert _ids(listed) == [str(allocation_id)]
    assert _ids(default) == []
    body = _json(report)
    assert body["trade_count"] == 0
    assert Decimal(body["total_pnl"]) == 0
    assert body["excluded"]["rehearsal_fill_count"] == 2


async def test_the_cursor_pages_across_both_kinds_exactly_once_with_a_limit_of_two(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger
    seen: list[str] = []
    cursors: list[dict[str, Any] | None] = []
    params: dict[str, Any] = {"include_rehearsal": "true", "limit": 2}

    for _ in range(10):
        page = await _list(client, ledger.strategy_id, **params)
        seen += _ids(page)
        cursors.append(page["next_cursor"])
        if page["next_cursor"] is None:
            break
        params = {**params, **page["next_cursor"]}

    assert seen == [
        str(a)
        for a in (
            ledger.opened_at_one_closed_at_alert,
            ledger.alert_of_one,
            ledger.alert_small,
            ledger.fixed_one,
            ledger.mixed,
            ledger.real_short,
            ledger.real_long,
        )
    ]
    assert [cursor is None for cursor in cursors] == [False, False, False, True]


async def test_include_rehearsal_that_is_not_a_boolean_is_422(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    response = await client.get(
        _trades_url(operations_ledger.strategy_id),
        headers=_auth(),
        params={"include_rehearsal": "maybe"},
    )

    assert response.status_code == 422


async def test_the_existing_refusals_are_unchanged(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    strategy = _trades_url(operations_ledger.strategy_id)
    half_cursor = await client.get(
        strategy, headers=_auth(), params={"before_allocation_id": str(uuid4())}
    )
    naive = await client.get(
        strategy,
        headers=_auth(),
        params={
            "before_closed_at": "2026-09-30T00:00:00",
            "before_allocation_id": str(uuid4()),
        },
    )
    too_many = await client.get(strategy, headers=_auth(), params={"limit": 201})
    unknown = await client.get(_trades_url(uuid4()), headers=_auth())

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "no such strategy"})
    assert half_cursor.status_code == 422
    assert naive.status_code == 422
    assert too_many.status_code == 422


# --- the list: refused reads -----------------------------------------------------------


def _rehearsal_group(strategy_id: UUID, allocation_id: UUID, **kwargs: Any) -> FillGroup:
    fields: dict[str, Any] = {
        "allocation_id": allocation_id,
        "strategy_id": strategy_id,
        "exchange": "bybit",
        "venue": "usdt-m",
        "settlement_currency": "USDT",
        "symbol": "STXUSDT.P",
        "side": "BUY",
        "fee_currency": "USDT",
        "quantity": Decimal("1"),
        "notional": Decimal("1"),
        "fee": Decimal("0"),
        "first_filled_at": _hours(0),
        "last_filled_at": _hours(0),
        "pool_total_at_open": Decimal("1000"),
        "rehearsal": True,
    }
    fields.update(kwargs)
    return FillGroup(**fields)


async def test_a_source_that_puts_a_rehearsal_group_in_the_live_set_is_a_500_and_one_logged_error(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """The twin of the test that refuses another pool's rows: a rehearsal group in
    the live set would put dry-run money into a real figure, so the read raises."""
    strategy_id = await _strategy(pg_session_factory)
    stray = _rehearsal_group(strategy_id, uuid4())
    app = _app(pg_session_factory)
    app.dependency_overrides[get_fills_source] = lambda: FakeFillsSource([stray])

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get(_trades_url(strategy_id), headers=_auth())

    assert response.status_code == 500
    assert response.json() == {"detail": "performance data failed an integrity check"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "rehearsal" in errors[0].getMessage()


async def test_a_rehearsal_row_with_a_non_positive_capital_is_the_existing_500(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    allocation_id = uuid4()
    round_trip = [
        _rehearsal_group(strategy_id, allocation_id, side="BUY", pool_total_at_open=Decimal(0)),
        _rehearsal_group(
            strategy_id, allocation_id, side="SELL", pool_total_at_open=Decimal(0),
            first_filled_at=_hours(1), last_filled_at=_hours(1),
        ),
    ]
    app = _app(pg_session_factory)
    app.dependency_overrides[get_fills_source] = lambda: FakeFillsSource(
        [], rehearsal_groups=round_trip
    )

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get(
                _trades_url(strategy_id), headers=_auth(), params={"include_rehearsal": "true"}
            )

    assert response.status_code == 500
    assert response.json() == {"detail": "performance data failed an integrity check"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "non-positive pool capital" in errors[0].getMessage()


# --- the fills route -------------------------------------------------------------------


def _fills_url(strategy_id: UUID, allocation_id: UUID) -> str:
    return f"{_trades_url(strategy_id)}/{allocation_id}/fills"


async def _fills(
    client: AsyncClient, strategy_id: UUID, allocation_id: UUID
) -> dict[str, Any]:
    response = await client.get(_fills_url(strategy_id, allocation_id), headers=_auth())
    assert response.status_code == 200, response.text
    return dict(_json(response))


def _fill_row(
    at: datetime, side: str, quantity: str, price: str, fee: str, *, rehearsal: bool = False
) -> dict[str, Any]:
    return {
        "filled_at": _iso(at),
        "side": side,
        "price": price,
        "quantity": quantity,
        "fee": fee,
        "fee_currency": "USDT",
        "rehearsal": rehearsal,
    }


async def test_the_fills_of_a_closed_operation_are_served_in_order(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    body = await _fills(client, ledger.strategy_id, ledger.real_long)

    assert body == {
        "allocation_id": str(ledger.real_long),
        "fills": [
            _fill_row(_hours(0), "BUY", "100.000000000000000000", "0.400000000000000000",
                      "0.100000000000000000"),
            _fill_row(_hours(0, 1), "BUY", "300.000000000000000000", "0.440000000000000000",
                      "0.100000000000000000"),
            _fill_row(_hours(0, 2), "BUY", "600.000000000000000000", "0.460000000000000000",
                      "0.100000000000000000"),
            _fill_row(_hours(1), "SELL", "1000.000000000000000000", "0.500000000000000000",
                      "0.100000000000000000"),
        ],
        "truncated": False,
    }


async def test_a_rehearsal_operations_fills_are_served_without_an_opt_in_each_flagged_true(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    body = await _fills(client, ledger.strategy_id, ledger.fixed_one)

    assert [(fill["side"], fill["rehearsal"]) for fill in body["fills"]] == [
        ("BUY", True),
        ("SELL", True),
    ]
    assert body["allocation_id"] == str(ledger.fixed_one)


async def test_a_mixed_allocation_answers_every_fill_with_its_own_flag(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    body = await _fills(client, ledger.strategy_id, ledger.mixed)

    assert [(fill["side"], fill["rehearsal"]) for fill in body["fills"]] == [
        ("BUY", False),
        ("SELL", False),
        ("BUY", True),
        ("SELL", True),
    ]


async def test_the_fills_of_both_spellings_of_the_symbol_are_in_the_answer(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    """The real operation opened as ``STXUSDT.P`` and closed as ``STXUSDT``; the
    rehearsal one opened as ``STXUSDT_PERP`` and closed as ``STXUSDT.P``. The route
    keys on the allocation, so every fill is there, and none carries a symbol."""
    ledger = operations_ledger

    real = await _fills(client, ledger.strategy_id, ledger.real_long)
    rehearsal = await _fills(client, ledger.strategy_id, ledger.fixed_one)

    assert [fill["side"] for fill in real["fills"]] == ["BUY", "BUY", "BUY", "SELL"]
    assert [fill["side"] for fill in rehearsal["fills"]] == ["BUY", "SELL"]
    assert not any("symbol" in fill for fill in real["fills"] + rehearsal["fills"])


async def test_more_than_200_fills_are_cut_and_flagged_and_exactly_200_are_not(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    allocations: dict[int, UUID] = {}
    for count in (200, 201):
        _, allocation_id, attempt_id = await _seed_allocation(
            pg_session_factory, strategy_id=strategy_id
        )
        allocations[count] = allocation_id
        await _record(
            pg_session_factory,
            *(
                _fill(strategy_id=strategy_id, allocation_id=allocation_id,
                      attempt_id=attempt_id, side="BUY", quantity="1",
                      filled_at=_hours(0) + timedelta(seconds=n))
                for n in range(count)
            ),
        )

    with caplog.at_level(logging.DEBUG, logger="strategy_manager.performance"):
        exactly = await _fills(client, strategy_id, allocations[200])
        silent = list(caplog.records)
        over = await _fills(client, strategy_id, allocations[201])

    assert (len(exactly["fills"]), exactly["truncated"]) == (200, False)
    assert (len(over["fills"]), over["truncated"]) == (200, True)
    assert over["fills"][0]["filled_at"] == _iso(_hours(0))
    assert over["fills"][-1]["filled_at"] == _iso(_hours(0) + timedelta(seconds=199))
    assert silent == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(strategy_id) in message
    assert str(allocations[201]) in message
    assert "200" in message


async def test_an_unknown_id_another_strategys_operation_and_an_empty_one_answer_the_same_404_and_the_same_body(  # noqa: E501
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    operations_ledger: OperationsLedger,
) -> None:
    ledger = operations_ledger
    _, no_fill, _ = await _seed_allocation(pg_session_factory, strategy_id=ledger.strategy_id)
    asked = {
        "unknown": uuid4(),
        "another strategy": ledger.other,
        "without a fill": no_fill,
    }

    answers = {
        name: await client.get(_fills_url(ledger.strategy_id, allocation_id), headers=_auth())
        for name, allocation_id in asked.items()
    }

    assert {name: (r.status_code, r.json()) for name, r in answers.items()} == {
        name: (404, {"detail": "no such operation"}) for name in asked
    }
    # S2's own read of that same allocation does answer, so the 404 above is the
    # strategy predicate at work and not an empty ledger.
    assert len((await _fills(client, ledger.other_strategy_id, ledger.other))["fills"]) == 2


async def test_an_unknown_strategy_is_a_different_404(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    response = await client.get(
        _fills_url(uuid4(), operations_ledger.real_long), headers=_auth()
    )

    assert (response.status_code, response.json()) == (404, {"detail": "no such strategy"})


async def test_an_allocation_id_that_is_not_a_uuid_is_422(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    response = await client.get(
        f"{_trades_url(operations_ledger.strategy_id)}/not-a-uuid/fills", headers=_auth()
    )

    assert response.status_code == 422


async def test_a_fill_in_another_pool_is_500_with_the_integrity_detail_and_no_fill_and_one_error(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    allocation_id = uuid4()
    stray = OperationFill(
        filled_at=_hours(0),
        side="BUY",
        price=Decimal("0.4512"),
        quantity=Decimal("1250"),
        fee=Decimal("0.31"),
        fee_currency="USDT",
        rehearsal=False,
        exchange="pionex",
        venue="spot",
        settlement_currency="USDT",
    )
    app = _app(pg_session_factory)
    app.dependency_overrides[get_operation_fills_source] = lambda: FakeOperationFillsSource(
        {(strategy_id, allocation_id): [stray]}
    )

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get(_fills_url(strategy_id, allocation_id), headers=_auth())

    assert response.status_code == 500
    assert response.json() == {"detail": "performance data failed an integrity check"}
    assert "0.4512" not in response.text
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "pools are never blended" in errors[0].getMessage()


async def test_an_open_allocations_fills_are_served(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    real = await _fills(client, ledger.strategy_id, ledger.open_real)
    rehearsal = await _fills(client, ledger.strategy_id, ledger.open_rehearsal)

    assert [(f["side"], f["rehearsal"]) for f in real["fills"]] == [("BUY", False)]
    assert [(f["side"], f["rehearsal"]) for f in rehearsal["fills"]] == [("BUY", True)]


async def test_the_body_carries_exactly_the_documented_keys(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    """No USD rate, venue order id, fill id, notional or symbol."""
    ledger = operations_ledger

    body = await _fills(client, ledger.strategy_id, ledger.real_short)

    assert set(body) == {"allocation_id", "fills", "truncated"}
    assert len(body["fills"]) == 2
    for fill in body["fills"]:
        assert set(fill) == {
            "filled_at", "side", "price", "quantity", "fee", "fee_currency", "rehearsal"
        }


async def test_the_404s_log_one_warning_naming_strategy_and_allocation(
    client: AsyncClient,
    operations_ledger: OperationsLedger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = operations_ledger
    unknown = uuid4()

    with caplog.at_level(logging.DEBUG):
        response = await client.get(_fills_url(ledger.strategy_id, unknown), headers=_auth())

    assert response.status_code == 404
    performance = [r for r in caplog.records if r.name.startswith("strategy_manager.performance")]
    assert [r.levelno for r in performance] == [logging.WARNING]
    message = performance[0].getMessage()
    assert str(ledger.strategy_id) in message
    assert str(unknown) in message


async def test_the_route_issues_the_same_number_of_statements_for_one_fill_and_for_fifty(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    counts: list[int] = []
    for n in (1, 50):
        _, allocation_id, attempt_id = await _seed_allocation(
            pg_session_factory, strategy_id=strategy_id
        )
        await _record(
            pg_session_factory,
            *(
                _fill(strategy_id=strategy_id, allocation_id=allocation_id,
                      attempt_id=attempt_id, side="BUY", quantity="1",
                      filled_at=_hours(0) + timedelta(seconds=i))
                for i in range(n)
            ),
        )
        with _captured_sql(pg_engine) as statements:
            body = await _fills(client, strategy_id, allocation_id)
        assert len(body["fills"]) == n
        counts.append(len(statements))

    # The strategy row, and the one SELECT of the fills.
    assert counts == [2, 2]


# --- authentication and the wire, over both routes -------------------------------------


async def test_the_trades_and_fills_routes_require_the_bearer_token(
    client: AsyncClient, operations_ledger: OperationsLedger
) -> None:
    """Both routes refuse a missing or a wrong token with the one 401, and neither
    exists outside ``/api``. The hand-written URL list of the pool route's own
    test is not touched: the new routes are discovered here, not assumed."""
    ledger = operations_ledger
    urls = [
        _trades_url(ledger.strategy_id),
        f"{_trades_url(ledger.strategy_id)}?include_rehearsal=true",
        _fills_url(ledger.strategy_id, ledger.real_long),
    ]
    for url in urls:
        missing = await client.get(url)
        wrong = await client.get(url, headers={"Authorization": "Bearer not-the-token"})
        admitted = await client.get(url, headers=_auth())
        pre_move = await client.get(url.removeprefix("/api"), headers=_auth())

        assert missing.status_code == 401, url
        assert wrong.status_code == 401, url
        assert missing.json()["detail"] == UNAUTHORIZED_DETAIL, url
        assert admitted.status_code == 200, url
        assert pre_move.status_code == 404, url
        # A refused request answers the one 401 body and nothing of the operation.
        assert "fills" not in missing.text and "entry_price" not in missing.text


async def test_no_trades_or_fills_response_contains_a_json_float_or_an_exponent(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    operations_ledger: OperationsLedger,
) -> None:
    """Every response of both routes over the one ledger is walked: the list as
    the older panel asks for it, with rehearsal rows, paged, and the fills of every
    operation. Money, quantities, prices and ratios are JSON strings in plain
    notation, never a number and never an exponent: the prices are quotients, so
    the rounding and the notation of ``Price`` are what is being proven here.

    One operation of the walk trades at a micro price (5E-7): a quotient that a
    bare ``str(Decimal)`` writes with an exponent, which no other price of the one
    ledger does."""
    ledger = operations_ledger
    _, micro, micro_attempt = await _seed_allocation(
        pg_session_factory, strategy_id=ledger.strategy_id
    )
    await _record(
        pg_session_factory,
        _fill(strategy_id=ledger.strategy_id, allocation_id=micro, attempt_id=micro_attempt,
              side="BUY", quantity="1000000", price="0.0000005", symbol="STXUSDT.P",
              filled_at=_hours(12)),
        _fill(strategy_id=ledger.strategy_id, allocation_id=micro, attempt_id=micro_attempt,
              side="SELL", quantity="1000000", price="0.0000006", symbol="STXUSDT",
              filled_at=_hours(13)),
    )
    allocations = (
        ledger.real_long, ledger.real_short, ledger.open_real, ledger.mixed,
        ledger.open_rehearsal, ledger.fixed_one, ledger.alert_small, ledger.alert_of_one,
        ledger.opened_at_one_closed_at_alert, micro,
    )
    requests: list[tuple[str, dict[str, Any]]] = [
        (_trades_url(ledger.strategy_id), {}),
        (_trades_url(ledger.strategy_id), {"include_rehearsal": "true"}),
        (_trades_url(ledger.strategy_id), {"include_rehearsal": "true", "limit": 2}),
        *((_fills_url(ledger.strategy_id, allocation), {}) for allocation in allocations),
    ]

    leaves: list[tuple[str, Any]] = []
    for url, params in requests:
        response = await client.get(url, headers=_auth(), params=params)
        assert response.status_code == 200, (url, params)
        leaves += [(f"{url} {params} {path}", value) for path, value in _walk(response.json())]

    micro_row = _row(
        dict(_json(await client.get(_trades_url(ledger.strategy_id), headers=_auth()))), micro
    )
    assert (micro_row["entry_price"], micro_row["exit_price"]) == (
        "0.000000500000000000",
        "0.000000600000000000",
    )
    assert len(leaves) > 300
    assert [(p, v) for p, v in leaves if isinstance(v, float)] == []
    numbers = 0
    for path, value in leaves:
        if isinstance(value, str):
            try:
                number = Decimal(value)
            except ArithmeticError:
                continue
            numbers += 1
            assert number.is_finite(), path
            assert "e" not in value.lower(), f"{path} is written in scientific notation: {value}"
        if path.endswith(("opened_at", "closed_at", "filled_at")) and value is not None:
            assert datetime.fromisoformat(value).utcoffset() == timedelta(0), path
            assert value.endswith("Z"), path
    assert numbers > 100
