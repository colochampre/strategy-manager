"""Decision 45 on real PostgreSQL (ORM schema): an order the simulated exchange
cannot price is refused through the venue-rejection path both use cases already
handle (spec: trade-execution § "An Order With No Usable Price Is Refused, Never
Defaulted"; § "A Market Not Quoted In USDT Is Refused In Dry Run").

The production use cases (``ClosePosition``, ``PlaceOrder``, ``SettleExecution``)
run on one real session over the production outcome adapters; only the
exchange is the simulated one. The fixtures and builders of
``test_order_outcomes_integration`` and ``test_settle_outcomes_integration`` are
imported as modules rather than copied.

What is asserted is what must NOT happen silently: no ledger row, the attempt
FAILED (or the reservation released), the signal ``REJECTED`` with the existing
reason code, exactly one ERROR line, and no credential, DSN or raw payload in
it.
"""

import logging
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.close_position import CloseCommand
from strategy_manager.execution.application.ports import OpenOrderSpec
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.signals.infrastructure import test_order_outcomes_integration as order_h
from tests.signals.infrastructure import test_settle_outcomes_integration as settle_h

pytestmark = pytest.mark.integration

_CLOSE_LOGGER = "strategy_manager.execution.application.close_position"
_PLACE_LOGGER = "strategy_manager.execution.application.place_order"
_SYMBOL = "STXUSDT.P"


class _ForgetfulExchange(FakeExchangeAdapter):
    """A simulated exchange whose build forgets the price it was given: the
    order it hands back is one it never remembered."""

    async def build_open_order(self, spec: OpenOrderSpec):  # type: ignore[no-untyped-def]
        order = await super().build_open_order(spec)
        self._reference_prices.pop(spec.client_order_id)
        return order


def _exchange(exchange: str = "bybit") -> FakeExchangeAdapter:
    return FakeExchangeAdapter(exchange=exchange, fee_rate=Decimal("0"))


def _close_command(
    strategy_id: UUID,
    allocation_id: UUID,
    signal_id: UUID | None,
    reference_price: Decimal | None,
) -> CloseCommand:
    return CloseCommand(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=_SYMBOL,
        side=OrderSide.SELL,
        signal_id=signal_id,
        reference_price=reference_price,
    )


async def _ledger_rows(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        count = select(func.count()).select_from(LedgerEntryRow)
        return (await session.execute(count)).scalar_one()


async def _close(
    factory: async_sessionmaker[AsyncSession],
    exchange: FakeExchangeAdapter,
    command: CloseCommand,
):  # type: ignore[no-untyped-def]
    async with factory() as session:
        return await settle_h._close_position(session, exchange).close(command)


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def _assert_one_clean_error(caplog: pytest.LogCaptureFixture, *needles: str) -> None:
    [record] = _errors(caplog)
    assert record.name == _CLOSE_LOGGER
    text = record.getMessage()
    assert "close rejected by venue" in text
    assert "the simulated exchange cannot price this order" in text
    for needle in needles:
        assert needle in text
    # Ids, the exchange, the symbol and the cause only.
    for forbidden in ("postgres", "password", "secret", "api_key", "DATABASE_URL"):
        assert forbidden not in text.lower()


async def test_a_close_with_no_reference_price_fails_the_attempt_rejects_the_signal_and_leaves_the_ledger_unchanged(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    strategy_id, _, closing_signal, allocation_id = await settle_h._seed_position(
        pg_session_factory, closing_position_size="0"
    )
    rows_before = await _ledger_rows(pg_session_factory)

    result = await _close(
        pg_session_factory,
        _exchange(),
        _close_command(strategy_id, allocation_id, closing_signal, None),
    )

    assert result.status == "FAILED"
    [attempt] = await order_h._closing_attempts(pg_session_factory, allocation_id)
    assert attempt.status == "FAILED"
    signal = await order_h._signal(pg_session_factory, closing_signal)
    assert signal.status == "REJECTED"
    assert signal.outcome_reason == "CLOSE_REJECTED_BY_VENUE"
    assert await _ledger_rows(pg_session_factory) == rows_before == 1
    _assert_one_clean_error(caplog, "reference price: None")


@pytest.mark.parametrize(
    ("price", "named"),
    [
        pytest.param(Decimal("0"), "reference price: 0", id="zero"),
        pytest.param(Decimal("-0.4633"), "reference price: -0.4633", id="negative"),
        pytest.param(Decimal("NaN"), "reference price: NaN", id="nan"),
        pytest.param(Decimal("Infinity"), "reference price: Infinity", id="infinite"),
    ],
)
async def test_zero_negative_nan_and_infinite_close_prices_are_each_refused_the_same_way(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    price: Decimal,
    named: str,
) -> None:
    caplog.set_level(logging.WARNING)
    strategy_id, _, closing_signal, allocation_id = await settle_h._seed_position(
        pg_session_factory, closing_position_size="0"
    )

    result = await _close(
        pg_session_factory,
        _exchange(),
        _close_command(strategy_id, allocation_id, closing_signal, price),
    )

    assert result.status == "FAILED"
    [attempt] = await order_h._closing_attempts(pg_session_factory, allocation_id)
    assert attempt.status == "FAILED"
    signal = await order_h._signal(pg_session_factory, closing_signal)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "CLOSE_REJECTED_BY_VENUE")
    assert await _ledger_rows(pg_session_factory) == 1
    _assert_one_clean_error(caplog, named)


async def test_a_refused_close_leaves_the_position_open_and_a_later_close_at_a_usable_price_nets_it_to_zero(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """What the orphan path does at the strategy's next opening alert: a second
    close of the same allocation, at that alert's price."""
    strategy_id, _, closing_signal, allocation_id = await settle_h._seed_position(
        pg_session_factory, closing_position_size="0"
    )
    exchange = _exchange()
    refused = await _close(
        pg_session_factory,
        exchange,
        _close_command(strategy_id, allocation_id, closing_signal, None),
    )
    assert refused.status == "FAILED"
    async with pg_session_factory() as session:
        held = ReadHeldBase(SqlAlchemyLedgerRepository(session))
        assert await held.net_base(allocation_id, "STX") == Decimal("1")  # still open

    placed = await _close(
        pg_session_factory,
        exchange,
        _close_command(strategy_id, allocation_id, None, Decimal("0.4633")),
    )

    assert placed.status == "PLACED"
    assert placed.execution_attempt_id is not None
    async with pg_session_factory() as session:
        commit = settle_h._FaultyCommit(session, fail_on=None)
        await settle_h._settle(session, commit, exchange).settle(placed.execution_attempt_id)
    async with pg_session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(LedgerEntryRow)
                    .where(LedgerEntryRow.allocation_id == allocation_id)
                    .order_by(LedgerEntryRow.filled_at)
                )
            ).scalars()
        )
        assert [row.price for row in rows][-1] == Decimal("0.4633")
        assert len(rows) == 2
        held = ReadHeldBase(SqlAlchemyLedgerRepository(session))
        assert await held.net_base(allocation_id, "STX") == Decimal("0")


async def test_an_orphan_close_refused_for_its_price_writes_no_outcome_on_any_signal(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    strategy_id, opening_signal, closing_signal, allocation_id = await settle_h._seed_position(
        pg_session_factory, closing_position_size="0"
    )

    result = await _close(
        pg_session_factory, _exchange(), _close_command(strategy_id, allocation_id, None, None)
    )

    assert result.status == "FAILED"
    [attempt] = await order_h._closing_attempts(pg_session_factory, allocation_id)
    assert attempt.status == "FAILED"
    assert attempt.signal_id is None
    for signal_id in (opening_signal, closing_signal):
        signal = await order_h._signal(pg_session_factory, signal_id)
        assert signal.outcome_reason is None
        assert signal.status != "REJECTED"
    _assert_one_clean_error(caplog)


async def test_an_order_the_exchange_did_not_build_is_refused_and_an_opening_reservation_is_released(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    _, signal_id, reservation_id = await order_h._seed_open(
        pg_session_factory, expires_at=order_h._NOW + order_h.timedelta(hours=1)
    )
    exchange = _ForgetfulExchange(exchange="bybit", fee_rate=Decimal("0"))

    async with pg_session_factory() as session:
        commit = order_h._FaultyCommit(session, fail_on=None)
        await order_h._place_order(session, commit, exchange).place(
            order_h._place_command(reservation_id)
        )

    signal = await order_h._signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "ORDER_REJECTED_BY_VENUE")
    assert (await order_h._reservation(pg_session_factory, reservation_id)).status == "RELEASED"
    assert await _ledger_rows(pg_session_factory) == 0
    [record] = _errors(caplog)
    assert record.name == _PLACE_LOGGER
    assert "order rejected by venue" in record.getMessage()
    assert "the simulated exchange cannot price this order" in record.getMessage()
