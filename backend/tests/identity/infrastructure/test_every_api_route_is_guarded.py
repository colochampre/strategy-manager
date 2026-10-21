"""Every ``/api`` route requires the admin, except ``/api/me`` (multi-user
design AD1; tasks.md A.7).

In PR A nothing is scoped by user yet, so a route open to any signed-in user
would show the owner's money to whoever Access lets in once sign-up opens. This
reads the routes the app actually serves, so a router added later without the
guard fails here, not in production.

``/webhook/tradingview`` and ``/health`` stay outside Access entirely: TradingView
cannot sign in, and rule 3 must not depend on Cloudflare.
"""

from collections.abc import Callable, Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts

from strategy_manager.identity.infrastructure.dependencies import require_admin, verified_email
from strategy_manager.main import create_app

OPEN_TO_ANY_USER = {"/api/me"}
OUTSIDE_ACCESS = {"/webhook/tradingview", "/health"}


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _calls(dependency)


def _routes() -> dict[str, set[Callable[..., Any]]]:
    """Path -> every dependency its requests run, the router's included.
    FastAPI 0.141 includes routers lazily, so ``app.routes`` alone hides every
    mounted router; ``iter_route_contexts`` resolves them with their prefix and
    their router-level dependencies (as ``test_no_pool_management_surface.py``
    does)."""
    routes: dict[str, set[Callable[..., Any]]] = {}
    for route in iter_route_contexts(create_app().routes):
        dependant = getattr(route, "dependant", None)
        if route.path is not None and isinstance(dependant, Dependant):
            routes.setdefault(route.path, set()).update(_calls(dependant))
    return routes


def test_every_api_route_but_me_requires_the_admin() -> None:
    routes = _routes()
    api = {path for path in routes if path.startswith("/api/")}

    unguarded = sorted(path for path in api - OPEN_TO_ANY_USER if require_admin not in routes[path])

    assert len(api) >= 20  # a walk that found nothing would pass for free
    assert unguarded == []


def test_me_requires_a_signed_in_user_and_not_the_admin() -> None:
    calls = _routes()["/api/me"]

    assert verified_email in calls
    assert require_admin not in calls


def test_the_webhook_and_health_ask_nobody_to_sign_in() -> None:
    routes = _routes()

    for path in OUTSIDE_ACCESS:
        assert verified_email not in routes[path]
        assert require_admin not in routes[path]
