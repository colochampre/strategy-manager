"""Unit tests: ``parse_webhook_origin`` (design.md, unit 12f addendum, sections F
and O; spec: admin-api "The Webhook's Origin Is Served By Its Own Route";
tasks.md 12f.9.3).

The cases are one shared list, ``webhook-origin.cases.json``, that the panel's
own test reads too: the backend's accepted values, normalised, are the panel's
accepted values, so the two checks cannot drift apart silently. This module only
READS the file.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from strategy_manager.signals.domain.webhook_origin import (
    InvalidWebhookOrigin,
    parse_webhook_origin,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASES_FILE = (
    _REPO_ROOT / "frontend" / "src" / "features" / "strategies" / "webhook-origin.cases.json"
)
_CASES: dict[str, Any] = json.loads(_CASES_FILE.read_text(encoding="utf-8"))
_ACCEPTED: list[dict[str, str]] = _CASES["accepted"]
_UNSET: list[str] = _CASES["unset"]
_REFUSED: list[str] = _CASES["refused"]


def _refusal(raw: str) -> InvalidWebhookOrigin | None:
    """The exception ``parse_webhook_origin`` raised, or ``None`` when it raised
    nothing, so that "no exception" is an assertion and not an accident."""
    try:
        parse_webhook_origin(raw)
    except InvalidWebhookOrigin as exc:
        return exc
    return None


def test_the_shared_list_is_not_empty() -> None:
    assert len(_ACCEPTED) >= 5
    assert len(_UNSET) == 1
    assert len(_REFUSED) >= 17


@pytest.mark.parametrize("case", _ACCEPTED, ids=lambda case: case["raw"])
def test_an_accepted_origin_is_normalised(case: dict[str, str]) -> None:
    assert parse_webhook_origin(case["raw"]) == case["origin"]


@pytest.mark.parametrize("raw", _UNSET, ids=repr)
def test_an_empty_value_is_unset_and_not_an_error(raw: str) -> None:
    assert parse_webhook_origin(raw) is None


@pytest.mark.parametrize("raw", _REFUSED, ids=repr)
def test_a_refused_value_raises_invalid_webhook_origin(raw: str) -> None:
    raised = _refusal(raw)

    assert type(raised) is InvalidWebhookOrigin


@pytest.mark.parametrize("raw", _REFUSED, ids=repr)
def test_a_refusal_carries_a_fixed_reason_and_never_the_value(raw: str) -> None:
    raised = _refusal(raw)

    assert type(raised) is InvalidWebhookOrigin
    message = str(raised)
    assert message != ""
    assert raw not in message
    assert "user:pass" not in message


def test_a_credential_is_refused_with_a_reason_that_names_neither_part() -> None:
    raised = _refusal("https://user:pass@example.org")

    assert type(raised) is InvalidWebhookOrigin
    message = str(raised)
    assert "user" not in message
    assert "pass" not in message
    assert "example.org" not in message
