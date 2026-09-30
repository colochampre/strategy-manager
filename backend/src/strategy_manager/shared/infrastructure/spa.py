"""Serving the operator panel from the API process (design.md section 13).

The panel is a single-page application built by Vite. This module mounts its
``dist`` directory on the same origin as ``/api``, which is what lets the panel
call the API with no CORS and lets one Cloudflare Access policy cover both.

Three things are decided here, and each one exists because the obvious version
is wrong:

1. **The catch-all must not answer for the system's own surface.** It matches any
   GET path, so ``/api/typo`` and ``/webhook/tradingview`` (POST-only, so Starlette
   records the GET as a partial match and keeps looking) would both fall through
   to it and be answered with ``index.html`` and a 200. A client that got HTML
   where it expected JSON would fail three layers away from the cause. The
   reserved prefixes answer the same 404 JSON FastAPI answers for any unknown path.

2. **A request path never names a file outside ``dist``.** The path is resolved
   and then checked with ``is_relative_to``. A string prefix comparison is not a
   containment check (``dist-evil`` starts with ``dist``), ``dist / "/abs"``
   REPLACES the base rather than appending to it, and on Windows a backslash is a
   separator. Only a resolved path inside the resolved root is served, which also
   covers a symlink inside ``dist`` that points out of it.

3. **The catch-all steps aside for every method but GET.** A GET-only route still
   PARTIALLY matches a POST, and Starlette lets a partial match pre-empt both the
   other routes' own 405 and the trailing-slash redirect. Returning no match for
   other methods keeps every non-GET request answered exactly as it was before the
   panel was mounted, the webhook's POST included (rule 3).

The mount is gated by ``Settings.panel_dist_dir``; empty mounts nothing.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.routing import APIRoute
from starlette.routing import Match
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation

logger = logging.getLogger(__name__)

#: Hashed build output. The name changes when the content does, so a browser may
#: keep it for a year and never ask again.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

#: The page itself is the one file whose name never changes, so it is the one
#: that must be revalidated: a cached copy would point at bundles a new build
#: has already removed.
REVALIDATE_CACHE_CONTROL = "no-cache"

#: design.md section 13. React sets styles through the CSSOM, which ``style-src``
#: does not block, and the fonts are self-hosted, so nothing needs an exception.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

_INDEX = "index.html"

#: Paths the catch-all must never answer. Compared after stripping leading
#: slashes, because ``//api/x`` reaches the handler as ``/api/x``.
_RESERVED_EXACT = frozenset({"api", "webhook"})
_RESERVED_PREFIXES = ("api/", "webhook/", "health")


def _is_reserved(path: str) -> bool:
    normalized = path.lstrip("/")
    return normalized in _RESERVED_EXACT or normalized.startswith(_RESERVED_PREFIXES)


def _file_inside(root: Path, relative: str) -> Path | None:
    """The regular file ``relative`` names under ``root``, or ``None``.

    ``root`` is already resolved. Every failure mode is ``None`` rather than an
    error: the caller answers the page for anything that is not a file inside
    ``dist``, so a probe learns nothing from the difference.
    """
    if not relative or "\x00" in relative:
        return None
    try:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            return None
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


class _ImmutableStaticFiles(StaticFiles):
    """``/assets``: hashed files, cached for a year."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
        return response


class _GetOnlyRoute(APIRoute):
    """Matches GET and nothing else. See point 3 of the module docstring."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and scope["method"] != "GET":
            return Match.NONE, {}
        return super().matches(scope)


def mount_panel(app: FastAPI, dist: Path) -> None:
    """Serves ``dist`` from ``app``. Call it AFTER every router is included.

    Nothing here touches the filesystem at mount time: whether ``dist`` is usable
    is ``assert_panel_dist_ready``'s question, asked at startup where its ERROR
    can reach the alert bridge. Mounting is also how ``create_app`` runs at import
    time, where a failure would be a traceback on stderr and no alert.
    """
    app.mount(
        "/assets",
        _ImmutableStaticFiles(directory=dist / "assets", check_dir=False),
        name="panel-assets",
    )

    def page_headers() -> dict[str, str]:
        return {
            "Cache-Control": REVALIDATE_CACHE_CONTROL,
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }

    async def panel(path: str) -> Response:
        if _is_reserved(path):
            raise HTTPException(status_code=404)

        root = dist.resolve()
        index = (root / _INDEX).resolve()
        if not index.is_file():
            logger.error(
                "the panel's index.html is gone from %s; every page request answers 404 "
                "until a build is put back",
                root,
            )
            raise HTTPException(status_code=404)

        target = _file_inside(root, path)
        if target is not None and target != index:
            return FileResponse(
                target,
                headers={
                    "Cache-Control": REVALIDATE_CACHE_CONTROL,
                    "X-Content-Type-Options": "nosniff",
                },
            )
        return FileResponse(index, headers=page_headers())

    app.router.add_api_route(
        "/{path:path}",
        panel,
        methods=["GET"],
        include_in_schema=False,
        route_class_override=_GetOnlyRoute,
    )


def assert_panel_dist_ready(settings: Settings) -> None:
    """Refuses to start when ``PANEL_DIST_DIR`` is set but holds no ``index.html``.

    The alternative is an API that starts, answers ``/api`` correctly, and serves
    the owner a 404 at the one URL they type: a failure that looks like the panel
    not existing. Empty means the panel is off and there is nothing to check.

    It logs its own ERROR, then raises. uvicorn reports a failed lifespan on its
    ``uvicorn`` logger, which does not propagate to the root logger the alert
    bridge is installed on, so a refusal that only raised would reach no alert
    channel (owner decision 29). The message names a directory, never a secret.
    """
    if not settings.panel_dist_dir:
        return

    index = Path(settings.panel_dist_dir) / _INDEX
    if index.is_file():
        return

    message = (
        f"PANEL_DIST_DIR is set to {settings.panel_dist_dir!r} but {_INDEX} is not a "
        "file there. Build the frontend (cd frontend && npm run build) and point "
        "PANEL_DIST_DIR at its dist directory, or unset PANEL_DIST_DIR to run "
        "without the panel."
    )
    logger.error("refusing to start: %s", message)
    raise InvariantViolation(message)
