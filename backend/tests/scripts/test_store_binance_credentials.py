"""``store_binance_credentials.py`` folded onto ``SaveCredential`` (task 6b.7).

Binance cannot be asked whether a key withdraws or trades (decisions 24 and 30),
so the OWNER says so, on the command line, with two flags. The properties that
matter, each proven by what the fakes recorded:

- without both flags the script exits 2 BEFORE the secret prompt, before a
  saver is built, and stores nothing;
- the flags are the only way to confirm: no environment variable, no ``--yes``,
  no default, no abbreviation;
- what reaches ``SaveCredential`` is exactly what the flags said;
- only the last four characters of a key are ever printed.

No real credential (rule 1). Output is captured into locals before any
assertion that names a key or a secret, so a failing assertion cannot echo one.
"""

import ast
from pathlib import Path

import pytest
import store_binance_credentials as script

from strategy_manager.accounts.application.save_credential import (
    Saved,
    SaveOutcome,
    SaveRefused,
)
from strategy_manager.accounts.domain.errors import KeyRejected
from strategy_manager.accounts.domain.exchange_credential import FactSource, KeyFacts
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations
from tests.accounts.fakes import (
    BINANCE_KEY,
    BINANCE_SECRET,
    BOTH,
    NOW,
    RecordingInspector,
    binance_credential,
)
from tests.scripts.store_fakes import ScriptSession

WITHDRAWALS_FLAG = "--confirm-withdrawals-disabled"
FUTURES_FLAG = "--confirm-futures-enabled"
BOTH_FLAGS = [WITHDRAWALS_FLAG, FUTURES_FLAG]


async def _run(session: ScriptSession, argv: list[str]) -> int:
    return await script.main(argv, prompt=session.prompt, make_saver=session.make_saver)


def _leaks(*texts: str) -> list[str]:
    return [
        name
        for name, value in (("key", BINANCE_KEY), ("secret", BINANCE_SECRET))
        if any(value in text for text in texts)
    ]


@pytest.mark.parametrize(
    ("argv", "missing", "present"),
    [
        ([], [WITHDRAWALS_FLAG, FUTURES_FLAG], []),
        ([WITHDRAWALS_FLAG], [FUTURES_FLAG], [WITHDRAWALS_FLAG]),
        ([FUTURES_FLAG], [WITHDRAWALS_FLAG], [FUTURES_FLAG]),
    ],
)
async def test_without_both_confirmation_flags_exits_2_names_the_missing_one_prompts_for_nothing_stores_nothing(  # noqa: E501
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    missing: list[str],
    present: list[str],
) -> None:
    session = ScriptSession(binance_credential())

    code = await _run(session, argv)

    captured = capsys.readouterr()
    assert code == 2
    for flag in missing:
        assert flag in captured.err
    for flag in present:
        assert flag not in captured.err
    assert captured.out == ""
    # Nothing was asked and nothing was built: the secret prompt never ran, no
    # saver (and so no master key, no database) was requested, nothing stored.
    assert session.prompt_calls == 0
    assert session.saver_requests == 0
    assert session.saves == []
    assert session.writer.stored == []
    assert session.inspector.calls == []


async def test_with_both_flags_saves_owner_confirmed_and_prints_last4_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(binance_credential())

    code = await _run(session, BOTH_FLAGS)

    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    stored = [facts for _, facts in session.writer.stored]
    assert code == 0
    assert session.prompt_calls == 1
    assert len(stored) == 1
    assert stored[0].trade_capability_source is FactSource.OWNER_CONFIRMED
    assert stored[0].withdraw_check is FactSource.OWNER_CONFIRMED
    assert stored[0].trade_confirmed_at == NOW
    assert stored[0].withdraw_confirmed_at == NOW
    assert session.inspector.calls == ["binance"]
    assert BINANCE_KEY[-4:] in out
    assert _leaks(out, err) == []


async def test_the_flags_reach_save_credential_exactly_as_given(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(binance_credential())

    await _run(session, [FUTURES_FLAG, WITHDRAWALS_FLAG])

    capsys.readouterr()
    assert [confirmations for _, confirmations in session.saves] == [BOTH]


@pytest.mark.parametrize(
    "name",
    [
        "CONFIRM_WITHDRAWALS_DISABLED",
        "CONFIRM_FUTURES_ENABLED",
        "WITHDRAWALS_DISABLED_CONFIRMED",
        "FUTURES_ENABLED_CONFIRMED",
        "YES",
        "ASSUME_YES",
        "CI",
    ],
)
async def test_an_environment_variable_is_not_a_way_to_confirm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    for candidate in (
        "CONFIRM_WITHDRAWALS_DISABLED",
        "CONFIRM_FUTURES_ENABLED",
        "WITHDRAWALS_DISABLED_CONFIRMED",
        "FUTURES_ENABLED_CONFIRMED",
        "YES",
        "ASSUME_YES",
        "CI",
    ):
        monkeypatch.setenv(candidate, "1")
    monkeypatch.setenv(name, "true")
    session = ScriptSession(binance_credential())

    code = await _run(session, [])

    capsys.readouterr()
    assert code == 2
    assert session.prompt_calls == 0
    assert session.saves == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--yes"],
        ["-y"],
        [*BOTH_FLAGS, "--yes"],
        ["--confirm"],
        ["--confirm-withdrawals", "--confirm-futures"],
        [WITHDRAWALS_FLAG, "--confirm-futures-enabled=1"],
    ],
)
async def test_no_other_flag_confirms_and_abbreviations_are_refused(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    session = ScriptSession(binance_credential())

    code = await _run(session, argv)

    capsys.readouterr()
    assert code == 2
    assert session.prompt_calls == 0
    assert session.saver_requests == 0
    assert session.saves == []


def test_no_flag_defaults_to_confirmed() -> None:
    parsed = script.build_parser().parse_args([])

    assert parsed.confirm_withdrawals_disabled is False
    assert parsed.confirm_futures_enabled is False


def test_the_script_never_reads_the_environment_for_a_confirmation() -> None:
    tree = ast.parse(Path(script.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "os" not in imported
    assert not attributes & {"environ", "getenv"}


def test_the_script_no_longer_calls_the_sapi_restrictions_endpoint() -> None:
    """The module docstring explains why; no CODE may reach for the endpoint."""
    tree = ast.parse(Path(script.__file__).read_text(encoding="utf-8"))
    tree.body = tree.body[1:]  # drop the module docstring
    code = ast.unparse(tree)

    assert "apiRestrictions" not in code
    assert "/sapi/" not in code
    assert "spot_transport" not in code


async def test_a_prompt_that_yields_no_credential_stores_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(None)

    code = await _run(session, BOTH_FLAGS)

    capsys.readouterr()
    assert code == 1
    assert session.prompt_calls == 1
    assert session.saves == []


async def test_a_master_key_problem_is_found_before_the_secret_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(binance_credential(), master_key_ok=False)

    code = await _run(session, BOTH_FLAGS)

    capsys.readouterr()
    assert code == 1
    assert session.saver_requests == 1
    assert session.prompt_calls == 0


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (SaveOutcome.KEY_REJECTED, "binance rejected the key (code -2015)"),
        (SaveOutcome.VENUE_UNREACHABLE, "binance could not be read (HTTP 503)"),
        (SaveOutcome.CONCURRENT_SAVE, "another save for binance was stored first"),
    ],
)
async def test_a_refusal_exits_1_names_the_outcome_and_says_nothing_was_stored(
    capsys: pytest.CaptureFixture[str], outcome: SaveOutcome, expected: str
) -> None:
    session = ScriptSession(binance_credential(), result=SaveRefused(outcome, expected))

    code = await _run(session, BOTH_FLAGS)

    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert code == 1
    assert outcome.value in err
    assert expected in err
    assert "nothing was stored" in err.lower()
    assert _leaks(out, err) == []


async def test_a_rejected_key_is_reported_through_the_real_policy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(
        binance_credential(),
        inspector=RecordingInspector(error=KeyRejected("binance rejected the key (code -2014)")),
    )

    code = await _run(session, BOTH_FLAGS)

    captured = capsys.readouterr()
    assert code == 1
    assert SaveOutcome.KEY_REJECTED.value in captured.err
    assert session.writer.stored == []


async def test_a_failed_decrypt_round_trip_exits_1_and_prints_no_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(
        binance_credential(),
        save_error=script.RoundTripFailed("stored credential did not survive a decrypt round trip"),
    )

    code = await _run(session, BOTH_FLAGS)

    captured = capsys.readouterr()
    assert code == 1
    assert "round trip" in captured.err
    assert _leaks(captured.out, captured.err) == []


async def test_a_saved_result_is_printed_without_the_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    facts = KeyFacts(
        trade_capable=True,
        trade_capability_source=FactSource.OWNER_CONFIRMED,
        trade_confirmed_at=NOW,
        withdraw_check=FactSource.OWNER_CONFIRMED,
        withdraw_confirmed_at=NOW,
        validated_at=NOW,
        internal_transfer=None,
    )
    session = ScriptSession(
        binance_credential(), result=Saved(last4="efgh", facts=facts, warnings=())
    )

    code = await _run(session, BOTH_FLAGS)

    captured = capsys.readouterr()
    assert code == 0
    assert "efgh" in captured.out
    assert "binance" in captured.out
    assert _leaks(captured.out, captured.err) == []


def test_confirmations_are_the_only_input_the_flags_build() -> None:
    parsed = script.build_parser().parse_args(BOTH_FLAGS)

    assert script.confirmations_from(parsed) == OwnerConfirmations(
        withdrawals_disabled=True, futures_enabled=True
    )


async def test_a_saved_binance_key_enables_the_binance_pool_through_the_use_case(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(binance_credential())

    code = await _run(session, BOTH_FLAGS)

    capsys.readouterr()
    assert code == 0
    assert session.pools.enabled == ["binance"]


async def test_a_refused_binance_save_enables_no_pool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptSession(
        binance_credential(),
        inspector=RecordingInspector(error=KeyRejected("binance rejected the key (code -2014)")),
    )

    code = await _run(session, BOTH_FLAGS)

    capsys.readouterr()
    assert code == 1
    assert session.pools.enabled == []
