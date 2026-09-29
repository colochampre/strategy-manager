"""``store_bybit_credentials.py`` folded onto ``SaveCredential`` (task 6b.7).

Bybit is verified server-side, so the script takes NO confirmation flag, and a
read-only key is stored with a warning instead of refused (decision 18): one
active key per exchange, read-only accepted. No real credential (rule 1); output
is captured into locals before any assertion that names a key or a secret.
"""

from pathlib import Path

import pytest
import store_bybit_credentials as script

from strategy_manager.accounts.application.save_credential import SaveOutcome
from strategy_manager.accounts.domain.errors import KeyRejected, VenueUnreachable
from strategy_manager.accounts.domain.exchange_credential import FactSource
from strategy_manager.accounts.domain.key_policy import (
    READ_ONLY_WARNING,
    OwnerConfirmations,
    PermissionSnapshot,
)
from tests.accounts.fakes import (
    BYBIT_KEY,
    BYBIT_SECRET,
    NOW,
    READ_ONLY_SNAPSHOT,
    TRANSFER_SNAPSHOT,
    RecordingInspector,
    bybit_credential,
)
from tests.scripts.store_fakes import ScriptSession


async def _run(session: ScriptSession, argv: list[str] | None = None) -> int:
    return await script.main(argv or [], prompt=session.prompt, make_saver=session.make_saver)


def _leaks(*texts: str) -> list[str]:
    return [
        name
        for name, value in (("key", BYBIT_KEY), ("secret", BYBIT_SECRET))
        if any(value in text for text in texts)
    ]


async def test_read_only_key_is_stored_with_a_warning_not_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(READ_ONLY_SNAPSHOT))

    code = await _run(session)

    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    stored = [facts for _, facts in session.writer.stored]
    assert code == 0
    assert len(stored) == 1
    assert stored[0].trade_capable is False
    assert stored[0].trade_capability_source is FactSource.VERIFIED
    assert READ_ONLY_WARNING in out
    assert "cannot trade" in out
    assert BYBIT_KEY[-4:] in out
    assert "REFUSED" not in err
    assert _leaks(out, err) == []


async def test_a_trading_key_is_stored_without_a_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(TRANSFER_SNAPSHOT))

    code = await _run(session)

    captured = capsys.readouterr()
    stored = [facts for _, facts in session.writer.stored]
    assert code == 0
    assert len(stored) == 1
    assert stored[0].trade_capable is True
    assert stored[0].validated_at == NOW
    assert stored[0].trade_confirmed_at is None
    assert READ_ONLY_WARNING not in captured.out
    assert BYBIT_KEY[-4:] in captured.out
    assert _leaks(captured.out, captured.err) == []


async def test_no_confirmation_reaches_the_use_case(capsys: pytest.CaptureFixture[str]) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(TRANSFER_SNAPSHOT))

    await _run(session)

    capsys.readouterr()
    assert [confirmations for _, confirmations in session.saves] == [OwnerConfirmations()]


@pytest.mark.parametrize(
    "argv",
    [
        ["--confirm-withdrawals-disabled"],
        ["--confirm-futures-enabled"],
        ["--confirm-withdrawals-disabled", "--confirm-futures-enabled"],
        ["--yes"],
    ],
)
async def test_bybit_takes_no_confirmation_flag(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(TRANSFER_SNAPSHOT))

    code = await _run(session, argv)

    capsys.readouterr()
    assert code == 2
    assert session.prompt_calls == 0
    assert session.saver_requests == 0
    assert session.writer.stored == []


async def test_a_withdraw_permission_is_refused_and_nothing_is_stored(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = PermissionSnapshot(
        wallet_permissions=frozenset({"AccountTransfer", "Withdraw"}), read_only=False
    )
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(snapshot))

    code = await _run(session)

    captured = capsys.readouterr()
    assert code == 1
    assert SaveOutcome.WITHDRAW_PERMISSION.value in captured.err
    assert "Withdraw" in captured.err
    assert "nothing was stored" in captured.err.lower()
    assert session.writer.stored == []
    assert _leaks(captured.out, captured.err) == []


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (KeyRejected("bybit rejected the key (code 10003)"), SaveOutcome.KEY_REJECTED),
        (VenueUnreachable("bybit could not be read (HTTP 503)"), SaveOutcome.VENUE_UNREACHABLE),
    ],
)
async def test_a_venue_refusal_is_reported_distinctly(
    capsys: pytest.CaptureFixture[str], error: Exception, outcome: SaveOutcome
) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(error=error))

    code = await _run(session)

    captured = capsys.readouterr()
    assert code == 1
    assert outcome.value in captured.err
    assert str(error) in captured.err
    assert session.writer.stored == []
    assert _leaks(captured.out, captured.err) == []


async def test_permissions_the_venue_did_not_report_are_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(bybit_credential(), inspector=RecordingInspector(PermissionSnapshot()))

    code = await _run(session)

    captured = capsys.readouterr()
    assert code == 1
    assert SaveOutcome.PERMISSIONS_UNAVAILABLE.value in captured.err
    assert session.writer.stored == []


async def test_a_prompt_that_yields_no_credential_stores_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(None)

    code = await _run(session)

    capsys.readouterr()
    assert code == 1
    assert session.saves == []


async def test_a_master_key_problem_is_found_before_the_secret_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(bybit_credential(), master_key_ok=False)

    code = await _run(session)

    capsys.readouterr()
    assert code == 1
    assert session.saver_requests == 1
    assert session.prompt_calls == 0


async def test_a_failed_decrypt_round_trip_exits_1_and_prints_no_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(
        bybit_credential(),
        save_error=script.RoundTripFailed("stored credential did not survive a decrypt round trip"),
    )

    code = await _run(session)

    captured = capsys.readouterr()
    assert code == 1
    assert "round trip" in captured.err
    assert _leaks(captured.out, captured.err) == []


def test_the_script_no_longer_calls_the_permission_endpoint_itself() -> None:
    source = Path(script.__file__).read_text(encoding="utf-8")

    assert "api_key_info" not in source
    assert "read_only_client" not in source
