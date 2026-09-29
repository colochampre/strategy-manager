"""``SaveCredential``: the one way an exchange key enters the vault (unit 6b).

Two layers. The refusal and fact-stamping rules run against fakes: a recording
inspector (so "no venue request was sent" is an assertion, not a hope), a
recording writer and a ticking clock. Rotation and the concurrent-save race run
on real PostgreSQL, because a fake unique index can always be made to behave.

No real credential anywhere (rule 1). Keys and secrets are assigned to locals
before any assertion that mentions them, so a failing assertion cannot echo one.

Test names carry the HTTP status the router (8a-3) will map each outcome to;
this use case returns a typed outcome and knows no status codes.
"""

import asyncio
import logging
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import CredentialWriterPort
from strategy_manager.accounts.application.save_credential import (
    SaveCredential,
    Saved,
    SaveOutcome,
    SaveRefused,
    SaveResult,
)
from strategy_manager.accounts.domain.errors import (
    ConcurrentCredentialSave,
    KeyRejected,
    VenueUnreachable,
)
from strategy_manager.accounts.domain.exchange_credential import (
    ExchangeCredential,
    FactSource,
    KeyFacts,
)
from strategy_manager.accounts.domain.key_policy import (
    FUTURES_CONFIRMATION,
    READ_ONLY_WARNING,
    WITHDRAWALS_CONFIRMATION,
    OwnerConfirmations,
    PermissionSnapshot,
    UnservedExchange,
)
from strategy_manager.accounts.infrastructure.credential_vault import (
    ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT,
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from tests.accounts.fakes import (
    BINANCE_KEY,
    BINANCE_SECRET,
    BOTH,
    BYBIT_KEY,
    BYBIT_SECRET,
    NEITHER,
    NOW,
    READ_ONLY_SNAPSHOT,
    TRADING_SNAPSHOT,
    TRANSFER_SNAPSHOT,
    RecordingCommit,
    RecordingInspector,
    RecordingWriter,
    TickingClock,
    as_writer,
    binance_credential,
    bybit_credential,
    registry_for,
)

LOGGER = "strategy_manager.accounts.application.save_credential"



class Harness:
    """One use case wired to fakes, with everything a test asserts on."""

    def __init__(
        self,
        inspector: RecordingInspector,
        writer: RecordingWriter | None = None,
        clock: TickingClock | None = None,
    ) -> None:
        self.inspector = inspector
        self.writer = writer or RecordingWriter()
        self.commit = RecordingCommit()
        self.use_case = SaveCredential(
            registry_for(inspector),
            as_writer(self.writer),
            self.commit,
            clock or TickingClock(),
        )

    async def save(
        self, credential: ExchangeCredential, confirmations: OwnerConfirmations = NEITHER
    ) -> SaveResult:
        return await self.use_case.execute(credential, confirmations)


def _saved(result: SaveResult) -> Saved:
    assert isinstance(result, Saved), f"expected SAVED, got {result.outcome}"
    return result


def _refused(result: SaveResult) -> SaveRefused:
    assert isinstance(result, SaveRefused), "expected a refusal, got SAVED"
    return result


# --------------------------------------------------------------------------
# Venue outcomes (8a, the live read)
# --------------------------------------------------------------------------


async def test_key_rejected_by_venue_refuses_stores_nothing_422() -> None:
    h = Harness(RecordingInspector(error=KeyRejected("binance rejected the key (code -2014)")))

    result = _refused(await h.save(binance_credential(), BOTH))

    assert result.outcome is SaveOutcome.KEY_REJECTED
    assert "-2014" in result.detail
    assert h.inspector.calls == ["binance"]
    assert h.writer.stored == []
    assert h.commit.commits == 0


async def test_venue_unreachable_reported_distinctly_502() -> None:
    h = Harness(RecordingInspector(error=VenueUnreachable("bybit could not be read (HTTP 503)")))

    result = _refused(await h.save(bybit_credential()))

    assert result.outcome is SaveOutcome.VENUE_UNREACHABLE
    assert result.outcome is not SaveOutcome.KEY_REJECTED
    assert "503" in result.detail
    assert h.inspector.calls == ["bybit"]
    assert h.writer.stored == []
    assert h.commit.commits == 0


# --------------------------------------------------------------------------
# Bybit: verified server-side
# --------------------------------------------------------------------------


async def test_withdraw_permission_refuses_stores_nothing_422() -> None:
    snapshot = PermissionSnapshot(
        wallet_permissions=frozenset({"AccountTransfer", "Withdraw"}), read_only=False
    )
    h = Harness(RecordingInspector(snapshot))

    result = _refused(await h.save(bybit_credential()))

    assert result.outcome is SaveOutcome.WITHDRAW_PERMISSION
    assert "Withdraw" in result.detail
    assert h.inspector.calls == ["bybit"]
    assert h.writer.stored == []
    assert h.commit.commits == 0


async def test_permissions_unavailable_refuses_stores_nothing_422() -> None:
    h = Harness(RecordingInspector(PermissionSnapshot()))

    result = _refused(await h.save(bybit_credential()))

    assert result.outcome is SaveOutcome.PERMISSIONS_UNAVAILABLE
    assert h.inspector.calls == ["bybit"]
    assert h.writer.stored == []
    assert h.commit.commits == 0


async def test_readonly_key_stored_trade_capable_false_warning_returned_200() -> None:
    h = Harness(RecordingInspector(READ_ONLY_SNAPSHOT))

    result = _saved(await h.save(bybit_credential()))

    assert result.warnings == (READ_ONLY_WARNING,)
    assert result.facts.trade_capable is False
    assert result.facts.trade_capability_source is FactSource.VERIFIED
    assert [facts for _, facts in h.writer.stored] == [result.facts]
    assert h.commit.commits == 1


async def test_trading_key_stored_no_warning_returned_200() -> None:
    h = Harness(RecordingInspector(TRANSFER_SNAPSHOT))

    result = _saved(await h.save(bybit_credential()))

    assert result.warnings == ()
    assert result.last4 == "abcd"
    assert result.facts.trade_capable is True
    assert result.facts.internal_transfer is True
    assert len(h.writer.stored) == 1
    assert h.commit.commits == 1


async def test_bybit_stores_verified_facts_and_no_confirmation_timestamps() -> None:
    h = Harness(RecordingInspector(TRADING_SNAPSHOT))

    result = _saved(await h.save(bybit_credential()))

    facts = result.facts
    assert facts.trade_capability_source is FactSource.VERIFIED
    assert facts.withdraw_check is FactSource.VERIFIED
    assert facts.trade_confirmed_at is None
    assert facts.withdraw_confirmed_at is None
    assert facts.validated_at == NOW
    assert facts.internal_transfer is False


@pytest.mark.parametrize(
    ("confirmations", "named"),
    [
        (OwnerConfirmations(withdrawals_disabled=True), WITHDRAWALS_CONFIRMATION),
        (OwnerConfirmations(futures_enabled=True), FUTURES_CONFIRMATION),
    ],
)
async def test_bybit_confirmation_true_refused_not_applicable_stores_nothing(
    confirmations: OwnerConfirmations, named: str
) -> None:
    h = Harness(RecordingInspector(TRADING_SNAPSHOT))

    result = _refused(await h.save(bybit_credential(), confirmations))

    assert result.outcome is SaveOutcome.CONFIRMATION_NOT_APPLICABLE
    assert named in result.detail
    assert h.inspector.calls == []
    assert h.writer.stored == []
    assert h.commit.commits == 0


# --------------------------------------------------------------------------
# Binance: owner-confirmed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confirmations", "missing"),
    [
        (NEITHER, (WITHDRAWALS_CONFIRMATION, FUTURES_CONFIRMATION)),
        (OwnerConfirmations(futures_enabled=True), (WITHDRAWALS_CONFIRMATION,)),
        (OwnerConfirmations(withdrawals_disabled=True), (FUTURES_CONFIRMATION,)),
    ],
)
async def test_binance_without_confirmations_refused_before_any_venue_call_stores_nothing(
    confirmations: OwnerConfirmations, missing: tuple[str, ...]
) -> None:
    h = Harness(RecordingInspector())

    result = _refused(await h.save(binance_credential(), confirmations))

    assert result.outcome is SaveOutcome.CONFIRMATION_REQUIRED
    assert result.missing == missing
    assert h.inspector.calls == []
    assert h.writer.stored == []
    assert h.commit.commits == 0


async def test_binance_with_both_confirmations_stores_owner_confirmed_with_server_clock_timestamps() -> None:  # noqa: E501
    clock = TickingClock(NOW)
    h = Harness(RecordingInspector(), clock=clock)

    result = _saved(await h.save(binance_credential(), BOTH))

    facts = result.facts
    assert facts.trade_capability_source is FactSource.OWNER_CONFIRMED
    assert facts.withdraw_check is FactSource.OWNER_CONFIRMED
    assert facts.trade_capable is True
    assert facts.internal_transfer is None
    # One instant for everything, and it is the server's: the ticking clock
    # would hand a second, different moment to a use case that asked twice.
    assert facts.trade_confirmed_at == NOW
    assert facts.withdraw_confirmed_at == NOW
    assert facts.validated_at == NOW
    assert clock.now() == NOW + timedelta(seconds=1)
    assert h.inspector.calls == ["binance"]
    assert result.warnings == ()
    assert h.commit.commits == 1


async def test_an_exchange_with_no_key_policy_raises_and_nothing_is_sent() -> None:
    h = Harness(RecordingInspector(TRADING_SNAPSHOT))
    pionex = ExchangeCredential(
        exchange="pionex", label="default", api_key="PIONEX-FAKE-KEY-abcd", api_secret="s"
    )

    with pytest.raises(UnservedExchange):
        await h.save(pionex)

    assert h.inspector.calls == []
    assert h.writer.stored == []


# --------------------------------------------------------------------------
# The race
# --------------------------------------------------------------------------


async def test_a_writer_that_lost_the_race_gives_concurrent_save_and_commits_nothing() -> None:
    writer = RecordingWriter(error=ConcurrentCredentialSave("lost"))
    h = Harness(RecordingInspector(TRADING_SNAPSHOT), writer=writer)

    result = _refused(await h.save(bybit_credential()))

    assert result.outcome is SaveOutcome.CONCURRENT_SAVE
    assert h.inspector.calls == ["bybit"]
    assert h.commit.commits == 0


def test_the_writer_port_has_no_load_the_save_path_never_decrypts() -> None:
    assert not hasattr(CredentialWriterPort, "load")
    assert hasattr(CredentialWriterPort, "store")


# --------------------------------------------------------------------------
# Logging: what fails here without a single log line?
# --------------------------------------------------------------------------


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


async def test_a_refusal_logs_exactly_one_warning_naming_the_exchange_and_the_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(RecordingInspector())
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await h.save(binance_credential(), NEITHER)

    records = _records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    line = records[0].getMessage()
    assert "binance" in line
    assert SaveOutcome.CONFIRMATION_REQUIRED.value in line


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (KeyRejected("bybit rejected the key (code 10003)"), SaveOutcome.KEY_REJECTED),
        (
            VenueUnreachable("bybit could not be read (transport failure)"),
            SaveOutcome.VENUE_UNREACHABLE,
        ),
    ],
)
async def test_venue_refusals_log_a_warning_never_an_error(
    caplog: pytest.LogCaptureFixture, error: Exception, outcome: SaveOutcome
) -> None:
    h = Harness(RecordingInspector(error=error))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await h.save(bybit_credential())

    records = _records(caplog)
    assert [r.levelno for r in records] == [logging.WARNING]
    line = records[0].getMessage()
    assert "bybit" in line
    assert outcome.value in line


async def test_a_lost_race_logs_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness(
        RecordingInspector(TRADING_SNAPSHOT),
        writer=RecordingWriter(error=ConcurrentCredentialSave("lost")),
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await h.save(bybit_credential())

    records = _records(caplog)
    assert [r.levelno for r in records] == [logging.WARNING]
    assert SaveOutcome.CONCURRENT_SAVE.value in records[0].getMessage()


async def test_a_save_logs_one_info_with_the_exchange_and_last4(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(RecordingInspector(TRADING_SNAPSHOT))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await h.save(bybit_credential())

    records = _records(caplog)
    assert [r.levelno for r in records] == [logging.INFO]
    line = records[0].getMessage()
    assert "bybit" in line
    assert "abcd" in line


async def test_no_log_line_carries_a_key_or_a_secret(caplog: pytest.LogCaptureFixture) -> None:
    saved = Harness(RecordingInspector(TRADING_SNAPSHOT))
    rejected = Harness(RecordingInspector(error=KeyRejected("bybit rejected the key (code 10003)")))
    with caplog.at_level(logging.DEBUG):
        await saved.save(bybit_credential())
        await rejected.save(bybit_credential())
        await Harness(RecordingInspector()).save(binance_credential(), NEITHER)

    text_logged = caplog.text
    leaked = [
        secret
        for secret in (BYBIT_KEY, BYBIT_SECRET, BINANCE_KEY, BINANCE_SECRET)
        if secret in text_logged
    ]
    assert text_logged  # the use case did log: an empty capture would prove nothing
    assert leaked == []


# --------------------------------------------------------------------------
# Real PostgreSQL: rotation and the race
# --------------------------------------------------------------------------


def _real_use_case(
    session: AsyncSession,
    master_key: bytes,
    inspector: RecordingInspector,
    clock: TickingClock,
) -> SaveCredential:
    return SaveCredential(
        registry_for(inspector),
        SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), clock),
        session,
        clock,
    )


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(MASTER_KEY_BYTES)


@pytest.fixture
async def clean_credentials(pg_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()


async def _rows(
    factory: async_sessionmaker[AsyncSession], exchange: str
) -> list[ExchangeCredentialRow]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(ExchangeCredentialRow)
                    .where(ExchangeCredentialRow.exchange == exchange)
                    .order_by(ExchangeCredentialRow.created_at, ExchangeCredentialRow.api_key_last4)
                )
            ).scalars()
        )


@pytest.mark.integration
@pytest.mark.usefixtures("clean_credentials")
async def test_rotation_deactivates_previous_row_retains_it(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    clock = TickingClock(NOW)
    async with pg_session_factory() as session:
        first = await _real_use_case(
            session, master_key, RecordingInspector(READ_ONLY_SNAPSHOT), clock
        ).execute(bybit_credential("BYBIT-OLD-KEY-1111"), NEITHER)
    async with pg_session_factory() as session:
        second = await _real_use_case(
            session, master_key, RecordingInspector(TRADING_SNAPSHOT), clock
        ).execute(bybit_credential("BYBIT-NEW-KEY-2222"), NEITHER)

    saved_first, saved_second = _saved(first), _saved(second)
    rows = await _rows(pg_session_factory, "bybit")
    by_last4 = {row.api_key_last4: row for row in rows}
    old, new = by_last4["1111"], by_last4["2222"]

    assert len(rows) == 2
    assert old.is_active is False
    assert new.is_active is True
    # The old row is kept exactly as it was recorded: rotation never rewrites
    # what was established about the previous key.
    assert old.trade_capable is False
    assert old.trade_capability_source == "VERIFIED"
    assert old.validated_at == saved_first.facts.validated_at
    assert old.internal_transfer is True
    assert new.trade_capable is True
    assert new.validated_at == saved_second.facts.validated_at
    assert new.internal_transfer is False


@pytest.mark.integration
@pytest.mark.usefixtures("clean_credentials")
async def test_rotation_never_inherits_the_previous_keys_confirmations(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    clock = TickingClock(NOW)
    async with pg_session_factory() as session:
        first = _saved(
            await _real_use_case(session, master_key, RecordingInspector(), clock).execute(
                binance_credential("BINANCE-OLD-KEY-1111"), BOTH
            )
        )
    async with pg_session_factory() as session:
        second = _saved(
            await _real_use_case(session, master_key, RecordingInspector(), clock).execute(
                binance_credential("BINANCE-NEW-KEY-2222"), BOTH
            )
        )

    rows = await _rows(pg_session_factory, "binance")
    by_last4 = {row.api_key_last4: row for row in rows}
    old, new = by_last4["1111"], by_last4["2222"]

    assert first.facts.trade_confirmed_at is not None
    assert second.facts.trade_confirmed_at is not None
    assert second.facts.trade_confirmed_at > first.facts.trade_confirmed_at
    assert old.trade_confirmed_at == first.facts.trade_confirmed_at
    assert old.withdraw_confirmed_at == first.facts.withdraw_confirmed_at
    assert new.trade_confirmed_at == second.facts.trade_confirmed_at
    assert new.withdraw_confirmed_at == second.facts.withdraw_confirmed_at
    assert new.trade_confirmed_at != old.trade_confirmed_at


@pytest.mark.integration
@pytest.mark.usefixtures("clean_credentials")
async def test_rotating_binance_without_confirmations_leaves_the_active_key_untouched(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """The refusal comes before any write: a rotation that cannot be stored
    must not deactivate the key the worker trades with."""
    clock = TickingClock(NOW)
    async with pg_session_factory() as session:
        _saved(
            await _real_use_case(session, master_key, RecordingInspector(), clock).execute(
                binance_credential("BINANCE-OLD-KEY-1111"), BOTH
            )
        )
    async with pg_session_factory() as session:
        refused = _refused(
            await _real_use_case(session, master_key, RecordingInspector(), clock).execute(
                binance_credential("BINANCE-NEW-KEY-2222"), NEITHER
            )
        )

    rows = await _rows(pg_session_factory, "binance")

    assert refused.outcome is SaveOutcome.CONFIRMATION_REQUIRED
    assert [(row.api_key_last4, row.is_active) for row in rows] == [("1111", True)]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_credentials")
async def test_concurrent_save_second_refused_409_by_constraint_name_not_message(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """Two saves race for the same exchange. The winner holds its transaction
    open after the insert; the loser must WAIT on the unique index (Postgres's
    own lock, held by the winner's open transaction), and only when the winner
    commits does it learn it lost.

    A lock-hold makes sense here, and it needs no wrapper: the lock under test
    is the unique index's, and an open uncommitted insert IS the hold. Two
    sessions racing without the hold could pass by luck of scheduling; with it,
    ``not task.done()`` proves the loser was blocked by the database.
    """
    assert ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT == "ux_exchange_credentials_one_active_per_exchange"
    clock = TickingClock(NOW)
    winner_facts = KeyFacts(
        trade_capable=True,
        trade_capability_source=FactSource.VERIFIED,
        trade_confirmed_at=None,
        withdraw_check=FactSource.VERIFIED,
        withdraw_confirmed_at=None,
        validated_at=NOW,
        internal_transfer=False,
    )

    async def loser() -> SaveResult:
        async with pg_session_factory() as session:
            return await _real_use_case(
                session, master_key, RecordingInspector(TRADING_SNAPSHOT), clock
            ).execute(bybit_credential("BYBIT-LOSER-KEY-2222"), NEITHER)

    async with pg_session_factory() as winner:
        vault = SqlAlchemyCredentialVault(winner, EnvelopeCipher(master_key), clock)
        await vault.store(bybit_credential("BYBIT-WINNER-KEY-1111"), winner_facts)

        task = asyncio.create_task(loser())
        await asyncio.wait({task}, timeout=1.0)
        still_waiting = not task.done()

        await winner.commit()
        (outcome,) = await asyncio.gather(task, return_exceptions=True)

    assert still_waiting, "the second save was not blocked by the winner's open insert"
    assert not isinstance(outcome, BaseException), type(outcome).__name__
    assert _refused(outcome).outcome is SaveOutcome.CONCURRENT_SAVE

    rows = await _rows(pg_session_factory, "bybit")
    assert [(row.api_key_last4, row.is_active) for row in rows] == [("1111", True)]
