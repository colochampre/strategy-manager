"""Nothing on the API enables, disables or configures a pool (unit 6d, decision 21).

Users never manage pools: there is no "activate pool" step and no screen.
``min_order_size`` is system configuration. The one way a pool switches on is
saving a key, and the one way it switches off is deleting one, both through the
credential routes.

The inventory comes from the application's own route table. FastAPI 0.141
includes routers lazily, so ``app.routes`` alone would hide every router mounted
that way; ``iter_route_contexts`` resolves them, with the prefix each was
mounted under, the same walk ``test_webhook_secret_router.py`` uses.
"""

from fastapi.routing import iter_route_contexts

from strategy_manager.main import create_app

READ_ONLY = {"GET", "HEAD", "OPTIONS"}
POOL_WORDS = ("pool", "capital", "min-order", "min_order")


def _api_routes() -> list[tuple[str, str]]:
    return sorted(
        (method, route.path)
        for route in iter_route_contexts(create_app().routes)
        if route.path is not None and route.path.startswith("/api") and route.methods
        for method in route.methods
    )


def test_the_route_walk_sees_the_pool_listing_it_is_meant_to_police() -> None:
    """A walk that found nothing would make the test below pass for free."""
    routes = _api_routes()

    assert ("GET", "/api/pools") in routes
    assert ("PUT", "/api/credentials/{exchange}") in routes
    assert len(routes) > 10


def test_no_endpoint_or_view_enables_disables_or_configures_a_pool_directly() -> None:
    writes_to_a_pool = [
        (method, path)
        for method, path in _api_routes()
        if method not in READ_ONLY and any(word in path.lower() for word in POOL_WORDS)
    ]

    assert writes_to_a_pool == []


def test_no_pool_route_accepts_a_body_that_could_name_a_pool() -> None:
    """Read-only is the whole surface under ``/api/pools``: a route there with
    any method beyond GET would be a management endpoint by another name."""
    methods = {method for method, path in _api_routes() if path.startswith("/api/pools")}

    assert methods <= READ_ONLY
