"""Composition-root wiring of ``TradeCapabilityPort`` (unit 6c, design.md § 4a).

Which adapter answers "can this exchange's key trade?" is a ``DRY_RUN``
decision, made where the exchange adapters are chosen: the worker's
``_build_process_signal_handler``. Under ``DRY_RUN`` the fake exchange places
nothing, so every exchange must answer ``TRADE_CAPABLE``; live, the answer comes
from the vault's recorded column. Getting either wrong is silent: a live worker
wired to the dry-run answer places orders on read-only keys, and a rehearsal
wired to the vault refuses every signal on a machine with no key.

No database is opened: the handler is only constructed, and constructing a
repository over an unconnected session performs no I/O.
"""

import inspect

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from strategy_manager import main
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    DryRunTradeCapability,
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
    handler, _ = main._build_process_signal_handler(
        session,
        {},
        settings,
        object(),  # type: ignore[arg-type]
        frozenset(),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    return handler._trade_capability  # type: ignore[attr-defined]


def test_dry_run_true_wires_the_dry_run_capability() -> None:
    assert isinstance(_handler_for(dry_run=True), DryRunTradeCapability)


def test_dry_run_false_wires_the_vault_capability() -> None:
    assert isinstance(_handler_for(dry_run=False), VaultTradeCapabilityAdapter)


def test_every_handler_build_takes_the_capability_from_the_same_dry_run_switch() -> None:
    """Both job handlers that build the handler (``signal.process`` and the
    open-after-close continuation) go through the one builder, so the
    continuation cannot end up with a different answer than the first pass."""
    source = inspect.getsource(main.build_worker_runner)
    assert source.count("_build_process_signal_handler(") == 2
    assert "VaultTradeCapabilityAdapter" not in source
    assert "DryRunTradeCapability" not in source

