"""A 422 must never echo what the client submitted (tasks.md 6b.3, design 8a § H).

FastAPI's default ``RequestValidationError`` answer carries, per error, the
offending ``input`` and a ``ctx`` that can hold the validator's own exception.
For ``PUT /api/credentials/{exchange}`` the body is an API key and its secret,
so a mistyped field would write the secret into the response, then into any
proxy, browser devtools or error tracker between here and the operator.

The handler is one for the whole application, so it is tested from both sides:
against a tiny app whose body looks like the credential body (so every kind of
validation failure can be provoked), and against ``create_app()`` itself, to
prove it is the handler the real application installs.

Every value below is a sentinel. No real credential anywhere (rule 1).
"""

import json
import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.validation_errors import (
    redacted_validation_handler,
)

KEY = "SENTINEL-KEY-0f3a11"
SECRET = "SENTINEL-SECRET-9c1d77"
EXTRA = "SENTINEL-EXTRA-5b2e90"
TOKEN = "adm1n-t0ken"

ALLOWED_ERROR_KEYS = {"type", "loc", "msg"}


class _Body(BaseModel):
    """The shape of the credential body, plus two fields that provoke ``ctx``
    and a validator whose own message quotes the value."""

    model_config = ConfigDict(extra="forbid")

    api_key: str
    api_secret: SecretStr
    label: str = Field(default="default", max_length=8)
    tag: str | None = None

    @field_validator("tag")
    @classmethod
    def _tag_must_not_be_reserved(cls, value: str | None) -> str | None:
        if value is not None and value.startswith("reserved"):
            raise ValueError(f"tag {value} is reserved")
        return value


def _mini_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, redacted_validation_handler)

    @app.put("/things/{name}")
    async def put_thing(name: int, body: _Body) -> dict[str, str]:
        return {"name": str(name)}

    return app


def _good() -> dict[str, Any]:
    return {"api_key": KEY, "api_secret": SECRET}


_MALFORMED_JSON = '{"api_key": "' + KEY + '", "api_secret": "' + SECRET  # never closed

#: (id, raw request content, expected error type of the first error)
CASES: list[tuple[str, str, str]] = [
    ("malformed-json", _MALFORMED_JSON, "json_invalid"),
    (
        "wrong-type-object-as-secret",
        json.dumps({"api_key": KEY, "api_secret": {"nested": SECRET}}),
        "string_type",
    ),
    (
        "wrong-type-list-as-key",
        json.dumps({"api_key": [KEY, SECRET], "api_secret": SECRET}),
        "string_type",
    ),
    ("extra-field", json.dumps({**_good(), "surprise": EXTRA}), "extra_forbidden"),
    ("missing-field", json.dumps({"api_key": KEY}), "missing"),
    (
        "constraint-with-ctx",
        json.dumps({**_good(), "label": SECRET}),
        "string_too_long",
    ),
    (
        "validator-quotes-the-value",
        json.dumps({**_good(), "tag": "reserved-" + SECRET}),
        "value_error",
    ),
]

_CASE_IDS = [case[0] for case in CASES]


async def _put(app: FastAPI, path: str, content: str, headers: dict[str, str] | None = None) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        return await api.put(
            path,
            content=content,
            headers={"Content-Type": "application/json", **(headers or {})},
        )


@pytest.mark.parametrize(("case", "content", "error_type"), CASES, ids=_CASE_IDS)
async def test_422_never_echoes_api_secret_input_or_ctx(
    case: str, content: str, error_type: str
) -> None:
    response = await _put(_mini_app(), "/things/7", content)

    assert response.status_code == 422, case
    for sentinel in (KEY, SECRET, EXTRA):
        assert sentinel not in response.text, f"{case}: {sentinel} was echoed"

    errors = response.json()["detail"]
    assert errors, "a 422 with no errors would prove nothing"
    for error in errors:
        assert set(error) <= ALLOWED_ERROR_KEYS, f"{case}: {sorted(error)}"
        assert "input" not in error
        assert "ctx" not in error
    assert errors[0]["type"] == error_type


async def test_422_still_says_which_field_and_what_kind_of_mistake() -> None:
    """Redaction must not turn the answer into an unhelpful blank: an operator
    fixing a mistyped field needs the field name and the rule it broke."""
    response = await _put(_mini_app(), "/things/7", json.dumps({"api_key": KEY}))

    assert response.status_code == 422
    assert response.json() == {
        "detail": [{"type": "missing", "loc": ["body", "api_secret"], "msg": "Field required"}]
    }


async def test_422_on_a_path_parameter_is_redacted_the_same_way() -> None:
    response = await _put(_mini_app(), "/things/" + SECRET, json.dumps(_good()))

    assert response.status_code == 422
    assert SECRET not in response.text
    assert [error["loc"] for error in response.json()["detail"]] == [["path", "name"]]


@pytest.mark.parametrize(("case", "content", "error_type"), CASES, ids=_CASE_IDS)
async def test_the_handler_never_logs_the_request_or_the_errors(
    case: str, content: str, error_type: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _put(_mini_app(), "/things/7", content)

    assert response.status_code == 422
    said = "\n".join(
        f"{record.getMessage()} {record.args} {record.msg}" for record in caplog.records
    )
    for sentinel in (KEY, SECRET, EXTRA):
        assert sentinel not in said, f"{case}: {sentinel} reached a log record"


# --- the real application ---------------------------------------------------------


def test_create_app_installs_the_redacted_handler_for_the_whole_app() -> None:
    handlers = create_app().exception_handlers

    assert handlers.get(RequestValidationError) is redacted_validation_handler


async def test_a_real_route_of_the_real_app_answers_a_redacted_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PATCH /api/strategies/{id}`` is an existing body route: its wrong-typed
    field is echoed by the default handler and must not be by this app."""
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    body = json.dumps({"name": {"nested": SECRET}, "enabled": SECRET})

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        response = await api.patch(
            "/api/strategies/5f0b2c1e-5b0b-4d7e-9f57-3a1f6f0f9c11",
            content=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 422
    assert SECRET not in response.text
    errors = response.json()["detail"]
    assert errors
    assert all(set(error) <= ALLOWED_ERROR_KEYS for error in errors)
