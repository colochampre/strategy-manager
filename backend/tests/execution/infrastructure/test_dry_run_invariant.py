"""``assert_dry_run_safe`` — spec: trade-execution § DRY_RUN Safety.

The dangerous configuration is not the one that looks broken. It is the one
where an operator deliberately turned DRY_RUN off, believes real orders are
going out, and gets fabricated fills at a fixed price instead.
"""

import pytest

from strategy_manager.execution.infrastructure.dry_run_invariant import (
    assert_dry_run_safe,
)
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.shared.domain.errors import InvariantViolation


class LiveExchange:
    """Stands in for a future real adapter."""

    is_live = True

    async def submit(self, order: object) -> object:  # pragma: no cover - never called
        raise NotImplementedError


def test_dry_run_with_a_fake_adapter_is_the_safe_default() -> None:
    assert_dry_run_safe(dry_run=True, exchange=FakeExchangeAdapter())


def test_live_trading_with_a_live_adapter_is_allowed() -> None:
    assert_dry_run_safe(dry_run=False, exchange=LiveExchange())  # type: ignore[arg-type]


def test_dry_run_with_a_live_adapter_is_allowed() -> None:
    """DRY_RUN is the safety switch: it may always be on, whatever is
    registered behind it."""
    assert_dry_run_safe(dry_run=True, exchange=LiveExchange())  # type: ignore[arg-type]


def test_live_trading_against_a_fake_adapter_fails_startup() -> None:
    with pytest.raises(InvariantViolation, match="not live"):
        assert_dry_run_safe(dry_run=False, exchange=FakeExchangeAdapter())


def test_the_failure_names_the_adapter_that_caused_it() -> None:
    """An operator reading this in a crash log needs to know which adapter was
    registered, not just that something was wrong."""
    with pytest.raises(InvariantViolation, match="FakeExchangeAdapter"):
        assert_dry_run_safe(dry_run=False, exchange=FakeExchangeAdapter())
