"""Integration: ``VaultTradeCapabilityAdapter`` against real PostgreSQL, and the
``DryRunTradeCapability`` that replaces it under ``DRY_RUN`` (design.md § 4a,
decisions 18, 20 and 30).

The adapter sits on the signal path ahead of the pool's advisory lock, so it
must answer from ONE column read of the active row and never decrypt anything
(rule 8: plaintext exists only in the worker at signing time). Every row below
carries garbage ciphertext on purpose: an adapter that tried to decrypt would
raise, and one that selected a ciphertext column shows up in the captured SQL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    DryRunTradeCapability,
    VaultTradeCapabilityAdapter,
)
from strategy_manager.signals.application.ports import TradeCapability

pytestmark = pytest.mark.integration

GARBAGE = b"\x00not-a-real-ciphertext\xff"
CONFIRMED_AT = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _clean(pg_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()


def _row(
    exchange: str,
    *,
    trade_capable: bool,
    source: str = "VERIFIED",
    active: bool = True,
) -> ExchangeCredentialRow:
    """A row whose every secret column is garbage. ``source`` decides which of
    the table's CHECK constraints the remaining fact columns must satisfy."""
    unrecorded = source == "UNRECORDED"
    confirmed = source == "OWNER_CONFIRMED"
    return ExchangeCredentialRow(
        exchange=exchange,
        label="default",
        is_active=active,
        wrapped_dek=GARBAGE,
        dek_nonce=GARBAGE,
        api_key_ciphertext=GARBAGE,
        api_key_nonce=GARBAGE,
        api_secret_ciphertext=GARBAGE,
        api_secret_nonce=GARBAGE,
        api_key_last4="abcd",
        trade_capable=trade_capable,
        trade_capability_source=source,
        trade_confirmed_at=CONFIRMED_AT if confirmed else None,
        withdraw_check=(
            "UNRECORDED" if unrecorded else ("OWNER_CONFIRMED" if confirmed else "VERIFIED")
        ),
        withdraw_confirmed_at=CONFIRMED_AT if confirmed else None,
        validated_at=None if unrecorded else CONFIRMED_AT,
        internal_transfer=None,
    )


async def _seed(
    factory: async_sessionmaker[AsyncSession], *rows: ExchangeCredentialRow
) -> None:
    async with factory() as session:
        session.add_all(rows)
        await session.commit()


async def _answer(factory: async_sessionmaker[AsyncSession], exchange: str) -> TradeCapability:
    async with factory() as session:
        return await VaultTradeCapabilityAdapter(session).capability(exchange)


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)


async def test_vault_adapter_answers_trade_capable_without_decrypting(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    """A row with garbage ciphertext still answers, and the one statement the
    adapter sends names no ciphertext, nonce or wrapped-key column."""
    await _seed(pg_session_factory, _row("bybit", trade_capable=True))

    with _captured_sql(pg_engine) as statements:
        answer = await _answer(pg_session_factory, "bybit")

    assert answer is TradeCapability.TRADE_CAPABLE
    assert len(statements) == 1
    sent = statements[0].lower()
    assert "trade_capable" in sent
    for secret_column in (
        "ciphertext",
        "nonce",
        "wrapped_dek",
    ):
        assert secret_column not in sent, secret_column


async def test_owner_confirmed_binance_row_answers_trade_capable(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Decision 30: a Binance key whose capability was only confirmed by the
    owner answers TRADE_CAPABLE. The adapter does not look at the source: the
    confirmation IS the source, and the venue is the backstop."""
    await _seed(
        pg_session_factory,
        _row("binance", trade_capable=True, source="OWNER_CONFIRMED"),
    )

    assert await _answer(pg_session_factory, "binance") is TradeCapability.TRADE_CAPABLE


async def test_unrecorded_row_answers_from_the_trade_capable_column(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A legacy (migration 0027) row states its capability in the column and
    nothing else: the column is the answer, in both directions."""
    await _seed(
        pg_session_factory,
        _row("bybit", trade_capable=False, source="UNRECORDED"),
        _row("binance", trade_capable=True, source="UNRECORDED"),
    )

    assert await _answer(pg_session_factory, "bybit") is TradeCapability.READ_ONLY
    assert await _answer(pg_session_factory, "binance") is TradeCapability.TRADE_CAPABLE


async def test_a_read_only_bybit_key_answers_read_only(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(pg_session_factory, _row("bybit", trade_capable=False))

    assert await _answer(pg_session_factory, "bybit") is TradeCapability.READ_ONLY


async def test_an_exchange_with_no_row_answers_no_key(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Never keyed: nothing to read is NO_KEY, not an error and not a default
    of TRADE_CAPABLE (a fallback is the failure this check prevents)."""
    assert await _answer(pg_session_factory, "bybit") is TradeCapability.NO_KEY


async def test_only_the_asked_exchanges_active_row_counts(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Another exchange's trade-capable key does not vouch for this one."""
    await _seed(pg_session_factory, _row("pionex", trade_capable=True))

    assert await _answer(pg_session_factory, "bybit") is TradeCapability.NO_KEY
    assert await _answer(pg_session_factory, "pionex") is TradeCapability.TRADE_CAPABLE


async def test_a_deactivated_row_is_no_key_immediately_after_the_delete(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Decision 22: once ``DeleteCredential`` deactivates the row the very next
    read says NO_KEY. A trade-capable history row must not answer for it."""
    await _seed(pg_session_factory, _row("bybit", trade_capable=True, active=False))

    assert await _answer(pg_session_factory, "bybit") is TradeCapability.NO_KEY


async def test_a_rotation_answers_from_the_new_active_row_not_the_history(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Replacing a trade-capable key with a read-only one is allowed (decision
    18): the superseded row must not keep the exchange trade-capable, and the
    reverse."""
    await _seed(
        pg_session_factory,
        _row("bybit", trade_capable=True, active=False),
        _row("bybit", trade_capable=False, active=True),
    )

    assert await _answer(pg_session_factory, "bybit") is TradeCapability.READ_ONLY


async def test_the_dry_run_adapter_always_answers_trade_capable() -> None:
    """``DRY_RUN`` places nothing, so no exchange is ever refused for its key:
    keyless, read-only or otherwise, and whatever name it is asked about."""
    adapter = DryRunTradeCapability()

    for exchange in ("bybit", "binance", "pionex", "anything"):
        assert await adapter.capability(exchange) is TradeCapability.TRADE_CAPABLE
