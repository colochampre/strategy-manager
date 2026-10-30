"""Composition-root wiring of ``TradeCapabilityPort`` (unit 6c, design.md § 4a;
multi-user design AD7, tasks.md E.4).

The vault's recorded column answers "can this exchange's key trade?", brake on or
off: what decides whether the question is asked is the opening's mode, not which
adapter is wired. A simulated opening never asks. Getting that wrong is silent: an
always-yes adapter behind a live opening places orders on read-only keys.

No database is opened: the handler is only constructed, and constructing a
repository over an unconnected session performs no I/O.
"""

import inspect

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from strategy_manager import main
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    VaultTradeCapabilityAdapter,
)
from strategy_manager.shared.config import Settings

_VALID_MASTER_KEY = "A" * 43 + "="


def _handler_for(dry_run: bool) -> object:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, dry_run=dry_run, master_encryption_key=_VALID_MASTER_KEY
    )
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@localhost:1/none")
    session = AsyncSession(engine)
    handler, _ = main._build_process_delivery(
        session,
        {},
        settings,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        {},
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    return handler._trade_capability  # type: ignore[attr-defined]


@pytest.mark.parametrize("dry_run", [True, False])
def test_the_vault_answers_whatever_the_brake(dry_run: bool) -> None:
    assert isinstance(_handler_for(dry_run=dry_run), VaultTradeCapabilityAdapter)


def test_every_handler_build_takes_the_capability_from_the_one_builder() -> None:
    """Both job handlers that build the handler (``delivery.process`` and the
    open-after-close continuation) go through the one builder, so the
    continuation cannot end up with a different answer than the first pass."""
    source = inspect.getsource(main.build_worker_runner)
    assert source.count("_build_process_delivery(") == 2
    assert "VaultTradeCapabilityAdapter" not in source

