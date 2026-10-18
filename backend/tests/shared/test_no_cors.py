"""CORS is removed: the panel is served by the API, so it is same-origin.

Owner decision 69 (2026-10-18), follow-up 7f.1. ``allow_credentials=True``
with a dev-server default origin was a production hazard for no benefit.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

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


def test_a_leftover_cors_origins_line_in_the_env_file_still_lets_settings_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Production's leftover is a LINE in ``.env``, and pydantic-settings applies
    the ``extra`` policy to dotenv entries only: an environment variable for an
    undeclared field is never read, so it could not prove anything. The file is
    a throwaway one; the real ``.env`` is never read here."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('CORS_ORIGINS=["http://localhost:5173"]\n', encoding="utf-8")

    class _Strict(Settings):
        model_config = SettingsConfigDict(extra="forbid")

    # The same file IS seen by the extra policy: a stricter subclass refuses it,
    # so the load below passes because ``Settings`` ignores the line, not
    # because nothing reached it.
    with pytest.raises(ValidationError):
        _Strict(_env_file=env_file)

    settings = Settings(_env_file=env_file)

    assert "cors_origins" not in settings.model_dump()
