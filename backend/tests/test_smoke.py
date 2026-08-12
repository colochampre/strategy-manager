"""Scaffold smoke tests.

These prove the toolchain runs and that the safety defaults are what we claim.
"""

from httpx import AsyncClient

from strategy_manager.shared.config import (
    TRADINGVIEW_SOURCE_IPS,
    TRADINGVIEW_TIMEOUT_SECONDS,
    Settings,
)


async def test_health_endpoint_responds(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dry_run_is_enabled_by_default() -> None:
    """The system must never place a real order unless dry-run is explicitly disabled."""
    settings = Settings(_env_file=None)

    assert settings.dry_run is True


def test_no_exchange_credentials_are_baked_in() -> None:
    """No credential may ship as a default value."""
    settings = Settings(_env_file=None)

    assert settings.webhook_secret == ""
    assert settings.master_encryption_key == ""


def test_tradingview_constraints_are_pinned() -> None:
    """These are external facts the ingress design depends on; pin them so a
    silent edit breaks a test rather than production."""
    documented_ips = {
        "52.89.214.238",
        "34.212.75.30",
        "54.218.53.128",
        "52.32.178.7",
    }

    assert TRADINGVIEW_TIMEOUT_SECONDS == 3.0
    assert TRADINGVIEW_SOURCE_IPS == documented_ips
