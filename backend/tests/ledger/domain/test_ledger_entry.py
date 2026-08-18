"""Unit tests for ``LedgerEntry`` — frozen, zero mutators (tasks.md 5.3;
spec: trade-ledger § Ledger Row Content, § Native Settlement-Currency
Reporting).
"""

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.shared.domain.errors import InvariantViolation


def _entry(**overrides: object) -> LedgerEntry:
    defaults: dict[str, object] = dict(
        id=uuid4(),
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
    return LedgerEntry(**defaults)  # type: ignore[arg-type]


def test_ledger_entry_is_frozen() -> None:
    entry = _entry()

    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.quantity = Decimal("1")  # type: ignore[misc]


def test_ledger_entry_has_no_mutator_methods() -> None:
    entry = _entry()
    public_methods = [
        name
        for name in dir(entry)
        if not name.startswith("_") and callable(getattr(entry, name))
    ]

    assert public_methods == []


def test_ledger_entry_carries_pool_and_ownership_fields() -> None:
    strategy_id = uuid4()
    allocation_id = uuid4()

    entry = _entry(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        venue="coin-m",
        settlement_currency="BTC",
    )

    assert entry.strategy_id == strategy_id
    assert entry.allocation_id == allocation_id
    assert entry.venue == "coin-m"
    assert entry.settlement_currency == "BTC"


def test_ledger_entry_rejects_non_positive_quantity() -> None:
    with pytest.raises(InvariantViolation):
        _entry(quantity=Decimal("0"))


def test_ledger_entry_rejects_non_positive_price() -> None:
    with pytest.raises(InvariantViolation):
        _entry(price=Decimal("0"))


def test_ledger_entry_rejects_negative_fee() -> None:
    with pytest.raises(InvariantViolation):
        _entry(fee=Decimal("-0.01"))


def test_ledger_entry_rejects_non_positive_usd_rate_at_fill() -> None:
    with pytest.raises(InvariantViolation):
        _entry(usd_rate_at_fill=Decimal("0"))
