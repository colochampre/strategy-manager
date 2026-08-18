"""``RecordFill`` implements ``execution.application.ports.FillRecorderPort``,
mapping ``FillRecord`` (incl. ``usd_rate_at_fill``) to a ``LedgerEntry`` and
writing it through a fake ``LedgerRepositoryPort`` (tasks.md 5.8).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry


@dataclass
class FakeLedgerRepository:
    inserted: list[LedgerEntry] = field(default_factory=list)

    async def insert(self, entry: LedgerEntry) -> None:
        self.inserted.append(entry)


def _fill_record(**overrides: object) -> FillRecord:
    defaults: dict[str, object] = dict(
        strategy_id=uuid4(),
        allocation_id=uuid4(),
        execution_attempt_id=uuid4(),
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.004"),
        price=Decimal("50000"),
        fee=Decimal("0.02"),
        fee_currency="USDT",
        notional=Decimal("200"),
        exchange_order_id="ex-order-1",
        exchange_fill_id="ex-fill-1",
        filled_at=datetime(2026, 8, 18, tzinfo=UTC),
        usd_rate_at_fill=Decimal("1"),
    )
    defaults.update(overrides)
    return FillRecord(**defaults)  # type: ignore[arg-type]


async def test_record_maps_fill_record_to_a_ledger_entry_and_inserts_it() -> None:
    repository = FakeLedgerRepository()
    record_fill = RecordFill(repository)
    strategy_id = uuid4()
    allocation_id = uuid4()
    execution_attempt_id = uuid4()
    fill_record = _fill_record(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=execution_attempt_id,
        usd_rate_at_fill=Decimal("0.9999"),
    )

    await record_fill.record(fill_record)

    assert len(repository.inserted) == 1
    entry = repository.inserted[0]
    assert entry.strategy_id == strategy_id
    assert entry.allocation_id == allocation_id
    assert entry.execution_attempt_id == execution_attempt_id
    assert entry.venue == "usdt-m"
    assert entry.settlement_currency == "USDT"
    assert entry.quantity == Decimal("0.004")
    assert entry.price == Decimal("50000")
    assert entry.usd_rate_at_fill == Decimal("0.9999")


async def test_record_generates_a_fresh_ledger_entry_id_each_time() -> None:
    repository = FakeLedgerRepository()
    record_fill = RecordFill(repository)

    await record_fill.record(_fill_record())
    await record_fill.record(_fill_record())

    ids = {entry.id for entry in repository.inserted}
    assert len(ids) == 2
