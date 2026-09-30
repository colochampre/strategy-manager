"""Serving the operator panel from the API process (design 13, tasks 4b.1-4b.4).

The harness is ``httpx.AsyncClient`` over the ASGI app with a temporary ``dist``
directory. It is a fixture standing in for a Vite build, not a build.

What these tests are really about is what the catch-all must NOT answer:

- ``/api``, ``/webhook`` and ``/health`` are the system's own surface. A path
  under them that no handler serves answers 404 JSON, never ``index.html``. The
  load-bearing case is ``GET /webhook/tradingview``: the route is POST-only, so
  Starlette records a method mismatch as a PARTIAL match and keeps looking, and a
  GET catch-all would then match in full and serve the page.
- a request path is never allowed to name a file outside ``dist``.
"""

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient, Response

from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings

TOKEN = "adm1n-t0ken"
WEBHOOK_SECRET = "wh-s3cret-spa-tests"

INDEX_MARKER = "INDEX-HTML-MARKER-7f3a"
SECRET_MARKER = "OUTSIDE-DIST-SECRET-91bc"
EVIL_MARKER = "SIBLING-DIR-SECRET-55de"
ASSET_BODY = "console.log('hashed asset');"

#: The design's string (design.md section 13), asserted verbatim on purpose: a
#: test that imported the constant would pass after any edit to it.
EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class Layout:
    """``tmp/dist`` is the served directory; everything else is outside it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dist = root / "dist"
        self.secret = root / "secret.txt"
        self.evil_dir = root / "dist-evil"


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    laid_out = Layout(tmp_path)
    (laid_out.dist / "assets").mkdir(parents=True)
    (laid_out.dist / "index.html").write_text(
        f"<!doctype html><title>panel</title>{INDEX_MARKER}", encoding="utf-8"
    )
    (laid_out.dist / "assets" / "app-abc123.js").write_text(ASSET_BODY, encoding="utf-8")
    (laid_out.dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    laid_out.secret.write_text(SECRET_MARKER, encoding="utf-8")
    laid_out.evil_dir.mkdir()
    (laid_out.evil_dir / "x.txt").write_text(EVIL_MARKER, encoding="utf-8")
    return laid_out


@pytest.fixture(autouse=True)
def _configure_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    monkeypatch.setattr(get_settings(), "webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(get_settings(), "panel_dist_dir", "")


@pytest.fixture
async def client(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(get_settings(), "panel_dist_dir", str(layout.dist))
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        yield api


def _is_index(response: Response) -> bool:
    return INDEX_MARKER in response.text


def _is_json_404(response: Response) -> bool:
    return (
        response.status_code == 404
        and response.headers["content-type"].startswith("application/json")
        and not _is_index(response)
    )


# --- 4b.1: the reserved prefixes never answer the page ---------------------------


async def test_get_api_unknown_returns_404_json_never_index_html(client: AsyncClient) -> None:
    for path in ("/api/nothing-here", "/api/strategies/x/y/z", "/api/"):
        response = await client.get(path)
        assert _is_json_404(response), path
        assert response.json() == {"detail": "Not Found"}, path


async def test_get_api_bare_returns_404_json(client: AsyncClient) -> None:
    response = await client.get("/api")

    assert _is_json_404(response)
    assert response.json() == {"detail": "Not Found"}


async def test_get_webhook_tradingview_via_get_returns_404_not_index_html(
    client: AsyncClient,
) -> None:
    """The method-mismatch case. The webhook route is POST-only."""
    response = await client.get("/webhook/tradingview")

    assert _is_json_404(response)
    assert response.json() == {"detail": "Not Found"}


async def test_other_paths_under_webhook_and_health_are_404_json(
    client: AsyncClient,
) -> None:
    # ``/%2Fapi/x`` is ``//api/x`` once decoded, and reaches the handler as
    # ``/api/x`` with its leading slash.
    for path in (
        "/webhook",
        "/webhook/",
        "/webhook/anything/else",
        "/health/x",
        "/healthz",
        "/%2Fapi/x",
        "/%2Fwebhook/tradingview",
    ):
        response = await client.get(path)
        assert _is_json_404(response), path


async def test_a_non_get_request_is_not_touched_by_the_catch_all(
    client: AsyncClient,
) -> None:
    """A plain GET-only route would turn these into 405 (Starlette records a
    method mismatch as a PARTIAL match, and a partial match also pre-empts the
    trailing-slash redirect), changing what the system answered before the mount
    for a method the page never uses. The catch-all steps aside for every
    method but GET, so they answer exactly as they did without it."""
    for method, path in (
        ("POST", "/api/nothing-here"),
        ("DELETE", "/api/nothing-here"),
        ("POST", "/webhook/nothing-here"),
        ("PUT", "/health/x"),
        ("POST", "/settings"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 404, (method, path)
        assert not _is_index(response), (method, path)

    wrong_method = await client.delete(
        "/api/webhook-secret", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert wrong_method.status_code == 405
    assert not _is_index(wrong_method)


async def test_existing_routes_still_answer_and_are_not_shadowed_by_the_catch_all(
    client: AsyncClient,
) -> None:
    """Behavioural proof that the catch-all is registered last: a handler
    registered before it must still be the one that answers."""
    health = await client.get("/health")
    secret = await client.get(
        "/api/webhook-secret", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    unauthenticated = await client.get("/api/webhook-secret")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "dry_run": get_settings().dry_run}
    assert secret.status_code == 200
    assert secret.json() == {"secret": WEBHOOK_SECRET}
    assert unauthenticated.status_code == 401
    assert not _is_index(unauthenticated)


def test_the_catch_all_is_the_last_route_and_the_only_one_outside_the_known_prefixes(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route sweep of the webhook-secret tests walks ``/api`` routes from the
    route table. This is the same walk with the panel mounted: the ``/api``
    surface is the same set, and the catch-all sits last and alone outside it."""
    bare = create_app()
    monkeypatch.setattr(get_settings(), "panel_dist_dir", str(layout.dist))
    mounted = create_app()

    def surface(app: object) -> list[tuple[str, frozenset[str]]]:
        return [
            (route.path, frozenset(route.methods))
            for route in iter_route_contexts(app.routes)  # type: ignore[attr-defined]
            if route.path is not None and route.methods
        ]

    bare_routes = surface(bare)
    mounted_routes = surface(mounted)

    assert mounted_routes[-1] == ("/{path:path}", frozenset({"GET"}))
    assert mounted_routes[:-1] == bare_routes
    assert [path for path, _ in bare_routes if path.startswith("/api")]  # walk is not vacuous
    assert not any(path.startswith("/api") for path, _ in mounted_routes[-1:])


async def test_an_unset_panel_dir_mounts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev, tests and today's production: no catch-all, no behaviour change."""
    monkeypatch.setattr(get_settings(), "panel_dist_dir", "")
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as bare:
        unknown = await bare.get("/settings")
        webhook_get = await bare.get("/webhook/tradingview")

    assert unknown.status_code == 404
    assert webhook_get.status_code == 405  # unchanged: the method mismatch


# --- 4b.2: client routes resolve to the page -------------------------------------


async def test_deep_client_route_strategies_uuid_resolves_to_index_html(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/strategies/{uuid4()}")

    assert response.status_code == 200
    assert _is_index(response)
    assert response.headers["content-type"].startswith("text/html")


async def test_settings_route_resolves_to_index_html_on_refresh(client: AsyncClient) -> None:
    for path in ("/settings", "/", "/strategies", "/some/deep/unknown/route"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert _is_index(response), path


async def test_a_root_level_file_is_served_as_itself_not_as_the_page(
    client: AsyncClient,
) -> None:
    response = await client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-cache"


# --- 4b.3: a path never leaves dist ----------------------------------------------


def _traversal_probes(layout: Layout) -> list[str]:
    absolute = layout.secret.resolve().as_posix()
    return [
        "/%2e%2e/secret.txt",
        "/%2E%2E/secret.txt",
        "/%2e%2e%2fsecret.txt",
        "/..%2fsecret.txt",
        "/..%2f..%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/..%2f..%2fsecret.txt",
        # Double-encoded: one decode leaves a literal "%2e%2e", which is just a
        # file name that does not exist.
        "/%252e%252e%252fsecret.txt",
        "/%252e%252e/secret.txt",
        # Backslashes are a separator on Windows, where ``dist / "..\\x"`` walks up.
        "/..%5csecret.txt",
        "/%2e%2e%5csecret.txt",
        "/..%5c..%5csecret.txt",
        # Absolute: ``dist / "/abs"`` REPLACES the base. The drive form is the
        # one that does so on Windows.
        "/" + quote(absolute, safe="/:"),
        "/" + quote(absolute, safe=""),
        "/%2F" + quote(absolute.lstrip("/"), safe=""),
    ]


async def test_path_traversal_encoded_dot_dot_never_escapes_dist(
    client: AsyncClient, layout: Layout
) -> None:
    for probe in _traversal_probes(layout)[:12]:
        response = await client.get(probe)
        assert SECRET_MARKER not in response.text, probe
        assert response.status_code in (200, 404), probe
        if response.status_code == 200:
            assert _is_index(response), probe


async def test_absolute_path_probe_never_escapes_dist(
    client: AsyncClient, layout: Layout
) -> None:
    for probe in _traversal_probes(layout)[12:]:
        response = await client.get(probe)
        assert SECRET_MARKER not in response.text, probe
        assert response.status_code in (200, 404), probe
        if response.status_code == 200:
            assert _is_index(response), probe


async def test_a_sibling_directory_sharing_the_dist_prefix_is_not_inside_dist(
    client: AsyncClient,
) -> None:
    """``dist-evil`` starts with the string ``dist``. A prefix comparison of the
    two paths says it is inside; ``is_relative_to`` says it is not."""
    for probe in ("/..%5cdist-evil%5cx.txt", "/..%2fdist-evil%2fx.txt"):
        response = await client.get(probe)
        assert EVIL_MARKER not in response.text, probe


def _link_directory(link: Path, target: Path) -> None:
    """A directory link inside ``dist``: a symlink where the account may create
    one, else a junction (Windows, no privilege needed). Skips when neither."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        made = subprocess.run(  # noqa: S603
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if made.returncode == 0 and link.exists():
            return
    pytest.skip("this account can create neither a symlink nor a junction")


async def test_a_link_inside_dist_pointing_outside_is_not_followed(
    client: AsyncClient, layout: Layout
) -> None:
    outside = layout.root / "outside"
    outside.mkdir()
    (outside / "linked.txt").write_text(SECRET_MARKER, encoding="utf-8")
    _link_directory(layout.dist / "leakdir", outside)

    response = await client.get("/leakdir/linked.txt")

    assert SECRET_MARKER not in response.text
    assert _is_index(response)


async def test_an_explicit_index_html_request_carries_the_page_headers(
    client: AsyncClient,
) -> None:
    response = await client.get("/index.html")

    assert _is_index(response)
    assert response.headers["content-security-policy"] == EXPECTED_CSP


# --- 4b.4: headers ---------------------------------------------------------------


async def test_hashed_asset_served_with_immutable_cache_control(client: AsyncClient) -> None:
    response = await client.get("/assets/app-abc123.js")

    assert response.status_code == 200
    assert response.text == ASSET_BODY
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_a_missing_asset_is_404_never_the_page(client: AsyncClient) -> None:
    """A stale tab asking for a chunk that a new build removed must fail, not
    receive HTML where it expects JavaScript."""
    response = await client.get("/assets/gone-deadbeef.js")

    assert response.status_code == 404
    assert not _is_index(response)
    assert "immutable" not in response.headers.get("cache-control", "")


async def test_index_html_served_with_no_cache_and_security_headers(
    client: AsyncClient,
) -> None:
    for path in ("/", "/settings", f"/strategies/{uuid4()}"):
        response = await client.get(path)
        assert response.headers["cache-control"] == "no-cache", path
        assert response.headers["content-security-policy"] == EXPECTED_CSP, path
        assert response.headers["x-content-type-options"] == "nosniff", path
        assert response.headers["referrer-policy"] == "no-referrer", path


async def test_api_responses_carry_none_of_the_panel_headers(client: AsyncClient) -> None:
    unauthorized = await client.get("/api/strategies")
    unknown = await client.get("/api/nothing-here")
    health = await client.get("/health")

    for response in (unauthorized, unknown, health):
        assert "content-security-policy" not in response.headers
        assert "referrer-policy" not in response.headers
        assert "immutable" not in response.headers.get("cache-control", "")
    assert unauthorized.status_code == 401


async def test_credentials_keep_no_store_with_the_panel_mounted(client: AsyncClient) -> None:
    refused = await client.get("/api/credentials")
    authorised = await client.get(
        "/api/credentials/nope", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert refused.status_code == 401
    assert refused.headers["cache-control"] == "no-store"
    assert authorised.headers["cache-control"] == "no-store"


# --- the webhook and /health are not changed by the mount ------------------------


async def test_the_catch_all_changes_nothing_for_the_webhook_post_or_health(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 3: the ingress validates, persists and answers inside three seconds.
    The same requests against the app with and without the panel must give the
    same status, body and headers, so the mount adds no work and no branch to
    the ingress path."""
    requests: list[tuple[str, str, dict[str, object] | None]] = [
        ("POST", "/webhook/tradingview", {"not": "a signal"}),
        ("POST", "/webhook/tradingview", None),
        ("POST", "/webhook/tradingview/", {"not": "a signal"}),
        ("GET", "/health", None),
    ]

    async def run() -> list[tuple[int, str, dict[str, str]]]:
        outcome: list[tuple[int, str, dict[str, str]]] = []
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as c:
            for method, path, body in requests:
                response = await c.request(method, path, json=body)
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key not in {"date"}
                }
                outcome.append((response.status_code, response.text, headers))
        return outcome

    without_panel = await run()
    monkeypatch.setattr(get_settings(), "panel_dist_dir", str(layout.dist))
    with_panel = await run()

    assert with_panel == without_panel
    # Not vacuous: these are real answers from the ingress, not the page.
    assert all(INDEX_MARKER not in text for _, text, _ in with_panel)
    assert with_panel[0][0] != 200
