"""The credential prompt never echoes the API key.

The Binance re-save of 2026-09-30 printed the full API key on the owner's
terminal, because the key was read with ``input()`` and only the secret with
``getpass()``. The key then travelled into a chat transcript. Both halves of a
credential are now read without echo, and no script under ``backend/scripts``
may call ``input()`` at all.
"""

import ast
import sys
from pathlib import Path

import credential_cli
import pytest

SCRIPTS_DIR = Path(credential_cli.__file__).resolve().parent

FAKE_KEY = "fake-api-key-0000000000000000000000000000000000000000000000abcd"
FAKE_SECRET = "fake-api-secret-000000000000000000000000000000000000000000wxyz"


def test_both_halves_of_the_credential_are_read_without_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hidden_prompts: list[str] = []
    answers = iter([FAKE_KEY, FAKE_SECRET])

    def fake_getpass(prompt: str = "") -> str:
        hidden_prompts.append(prompt)
        return next(answers)

    def echoing_input(prompt: str = "") -> str:
        raise AssertionError(f"input() echoes what is typed; it was called for {prompt!r}")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(credential_cli, "getpass", fake_getpass)
    monkeypatch.setattr("builtins.input", echoing_input)

    credential = credential_cli.prompt_credential(
        "binance", "Binance", "store_binance_credentials.py"
    )

    assert credential is not None
    assert credential.api_key == FAKE_KEY
    assert credential.api_secret == FAKE_SECRET
    assert len(hidden_prompts) == 2
    assert "key" in hidden_prompts[0].lower()
    assert "secret" in hidden_prompts[1].lower()
    out = capsys.readouterr()
    assert FAKE_KEY not in out.out + out.err
    assert FAKE_SECRET not in out.out + out.err


def _input_calls(path: Path) -> list[int]:
    # utf-8-sig: some scripts in this directory were saved with a BOM.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "input"
    ]


@pytest.mark.parametrize(
    "script", sorted(SCRIPTS_DIR.glob("*.py")), ids=lambda path: path.name
)
def test_no_script_reads_anything_with_an_echoing_input(script: Path) -> None:
    assert _input_calls(script) == [], f"{script.name} calls input(), which echoes"
