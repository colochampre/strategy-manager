"""Re-export of ``execution.domain.market_symbol.market_key``.

This module used to DEFINE ``market_key`` itself. It moved into
``execution/domain`` in migration 0024 (design.md § 6 "Normalization") so
that module owns the one real implementation the allowed-pairs seeding
migration's frozen copy is checked against
(``tests/migrations/test_0024_strategy_lifecycle.py``), without the
migration importing application code. This re-export keeps every existing
import path (``scan_pools.py``, ``prepare_booking.py``,
``reconciliation/infrastructure/router.py``) unchanged.
"""

from strategy_manager.execution.domain.market_symbol import market_key

__all__ = ["market_key"]
