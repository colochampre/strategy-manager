"""Every ``/api`` route requires the admin, except ``/api/me`` (multi-user
design AD1; tasks.md A.7).

In PR A nothing is scoped by user yet, so a route open to any signed-in user
would show the owner's money to whoever Access lets in once sign-up opens. This
reads the routes the app actually serves, so a router added later without the
guard fails here, not in production.

``/webhook/tradingview`` and ``/health`` stay outside Access entirely: TradingView
cannot sign in, and rule 3 must not depend on Cloudflare.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient

from strategy_manager.identity.infrastructure.dependencies import (
    FORBIDDEN_DETAIL,
    require_admin,
    verified_email,
)
from strategy_manager.main import create_app
from tests.identity_auth import OTHER_HEADERS, sign_in_as_admin

OPEN_TO_ANY_USER = {"/api/me"}
OUTSIDE_ACCESS = {"/webhook/tradingview", "/health"}


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _calls(dependency)


def _routes() -> dict[tuple[str, str], set[Callable[..., Any]]]:
    """(method, path) -> every dependency its requests run, the router's included.

    Keyed by method too, so a second router adding an unguarded method to a path
    another router guards is not hidden behind it. FastAPI 0.141 includes routers
    lazily, so ``app.routes`` alone hides every mounted router;
    ``iter_route_contexts`` resolves them with their prefix and their router-level
    dependencies (as ``test_no_pool_management_surface.py`` does). HEAD and
    OPTIONS are dropped: Starlette adds them around a declared method."""
    routes: dict[tuple[str, str], set[Callable[..., Any]]] = {}
    for route in iter_route_contexts(create_app().routes):
        dependant = getattr(route, "dependant", None)
        if route.path is None or not isinstance(dependant, Dependant):
            continue
        for method in set(route.methods or ()) - {"HEAD", "OPTIONS"}:
            routes.setdefault((method, route.path), set()).update(_calls(dependant))
    return routes


def _admin_only() -> list[tuple[str, str]]:
    return sorted(
        (method, path)
        for method, path in _routes()
        if path.startswith("/api/") and path not in OPEN_TO_ANY_USER
    )


def test_every_api_route_but_me_requires_the_admin() -> None:
    routes = _routes()
    admin_only = _admin_only()

    unguarded = [key for key in admin_only if require_admin not in routes[key]]

    assert len(admin_only) >= 20  # a walk that found nothing would pass for free
    assert unguarded == []


async def test_every_api_route_but_me_forbids_a_signed_in_user_who_is_not_the_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural walk above, proven by requests: one per (method, path) of
    every router, sent by a user Access signed in who is not the admin. No
    lifespan runs, so no handler could answer: the 403 is the guard's."""
    sign_in_as_admin(monkeypatch)
    admin_only = _admin_only()
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in admin_only:
            concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
            response = await client.request(method, concrete, headers=OTHER_HEADERS)

            assert response.status_code == 403, f"{method} {path}"
            assert response.json() == {"detail": FORBIDDEN_DETAIL}, f"{method} {path}"

    assert len(admin_only) >= 20


def test_me_requires_a_signed_in_user_and_not_the_admin() -> None:
    calls = _routes()[("GET", "/api/me")]

    assert verified_email in calls
    assert require_admin not in calls


def test_the_webhook_and_health_ask_nobody_to_sign_in() -> None:
    routes = _routes()
    outside = {key: calls for key, calls in routes.items() if key[1] in OUTSIDE_ACCESS}

    assert {path for _, path in outside} == OUTSIDE_ACCESS
    for calls in outside.values():
        assert verified_email not in calls
        assert require_admin not in calls
