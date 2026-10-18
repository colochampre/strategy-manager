"""CORS is removed: the panel is served by the API, so it is same-origin.

Owner decision 69 (2026-10-18), follow-up 7f.1. ``allow_credentials=True``
with a dev-server default origin was a production hazard for no benefit.
"""

import pytest
from httpx import AsyncClient

from strategy_manager.shared.config import Settings


async def test_a_preflight_to_an_api_route_gets_no_allow_origin_header(
    client: AsyncClient,
) -> None:
    response = await client.options(
        "/api/strategies",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_settings_has_no_cors_origins_field() -> None:
    assert "cors_origins" not in Settings.model_fields


def test_a_leftover_cors_origins_value_still_lets_settings_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173"]')

    settings = Settings(_env_file=None)

    assert settings.dry_run is True
