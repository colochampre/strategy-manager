"""API tests for ``GET /api/webhook-origin`` (design.md, unit 12f addendum,
section F; spec: admin-api "The Webhook's Origin Is Served By Its Own Route";
tasks.md 12f.9.4).

The route reads ``Settings.webhook_public_origin`` and answers the origin
``parse_webhook_origin`` makes of it, or ``null`` for an unset or a malformed
value. It needs no database. The cases of the shared list
(``webhook-origin.cases.json``) are the panel's own: accepted values are served
normalised, refused ones are served as ``null``.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from strategy_manager.main import create_app
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL

TOKEN = "adm1n-t0ken"
SECRET = "wh-s3cret-5b2e7a10-must-never-leak"
PATH = "/api/webhook-origin"

_CASES: dict[str, Any] = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "frontend"
        / "src"
        / "features"
        / "strategies"
        / "webhook-origin.cases.json"
    ).read_text(encoding="utf-8")
)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)
    monkeypatch.setattr(get_settings(), "webhook_public_origin", "")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        yield api


def _set_origin(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(get_settings(), "webhook_public_origin", value)


async def test_a_configured_origin_is_served(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_origin(monkeypatch, "https://example.duckdns.org")

    response = await client.get(PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"origin": "https://example.duckdns.org"}


async def test_an_unset_origin_is_served_as_null(client: AsyncClient) -> None:
    response = await client.get(PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"origin": None}


@pytest.mark.parametrize("case", _CASES["accepted"], ids=lambda case: case["raw"])
async def test_every_accepted_case_of_the_shared_list_is_served_normalised(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, case: dict[str, str]
) -> None:
    _set_origin(monkeypatch, case["raw"])

    response = await client.get(PATH, headers=_auth())

    assert response.json() == {"origin": case["origin"]}


@pytest.mark.parametrize("raw", _CASES["refused"], ids=repr)
async def test_every_refused_case_of_the_shared_list_is_served_as_null(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    _set_origin(monkeypatch, raw)

    response = await client.get(PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"origin": None}


async def test_a_malformed_value_does_not_stop_the_route_and_is_served_as_null(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_origin(monkeypatch, "https://user:pass@example.org")

    response = await client.get(PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"origin": None}
    assert "user:pass" not in response.text


async def test_the_body_never_contains_the_webhook_secret(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_origin(monkeypatch, "https://example.duckdns.org")

    response = await client.get(PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json()["origin"] == "https://example.duckdns.org"
    assert SECRET not in response.text
    assert SECRET not in "".join(f"{k}{v}" for k, v in response.headers.items())


async def test_the_route_requires_the_bearer_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing and a wrong token are the one 401, before the handler: the
    router carries the dependency, FastAPI does not re-apply the parent's."""
    _set_origin(monkeypatch, "https://example.duckdns.org")

    missing = await client.get(PATH)
    wrong = await client.get(PATH, headers={"Authorization": "Bearer not-the-token"})

    assert (missing.status_code, wrong.status_code) == (401, 401)
    assert missing.json() == {"detail": UNAUTHORIZED_DETAIL}
    assert wrong.json() == {"detail": UNAUTHORIZED_DETAIL}
    assert "example.duckdns.org" not in missing.text + wrong.text


def test_the_setting_defaults_to_empty() -> None:
    assert Settings.model_fields["webhook_public_origin"].default == ""
