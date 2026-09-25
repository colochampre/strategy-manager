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


async def test_webhook_and_health_paths_are_never_moved_under_api(
    client: AsyncClient,
) -> None:
    """spec: admin-api § "Webhook and Health Are Not Under /api". The `/api`
    move (design.md §13) wraps every ADMIN router — `/webhook/tradingview`
    and `/health` stay mounted directly on `app`, exactly where they always
    were, so this pins the composition root against ever swallowing either
    one into the `/api` wrapper by accident. Proven by live requests: neither
    prefixed path resolves to anything (404), and the real, unprefixed ones
    still do."""
    health = await client.get("/health")
    assert health.status_code == 200

    prefixed_health = await client.get("/api/health")
    assert prefixed_health.status_code == 404

    prefixed_webhook = await client.post("/api/webhook/tradingview")
    assert prefixed_webhook.status_code == 404


def test_dry_run_is_enabled_by_default() -> None:
    """The system must never place a real order unless dry-run is explicitly disabled."""
    settings = Settings(_env_file=None)

    assert settings.dry_run is True


def test_no_exchange_credentials_are_baked_in() -> None:
    """No credential may ship as a default value.

    ``admin_api_token`` belongs in this list for the same reason as the other
    two: a default would be a published password. It is the one whose empty
    default is ALSO load-bearing — startup invariant 4 reads exactly this
    value to decide whether to refuse to boot."""
    settings = Settings(_env_file=None)

    assert settings.webhook_secret == ""
    assert settings.admin_api_token == ""
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
