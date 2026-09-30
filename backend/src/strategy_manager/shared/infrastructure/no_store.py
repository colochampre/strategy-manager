"""``Cache-Control: no-store`` for every response under a path prefix.

The credentials routes answer the last four characters of a key and the facts
recorded about it. That is not a secret, but it is not something a browser or a
proxy should keep either.

A dependency that sets a header on the injected ``Response`` reaches only the
answers a route handler builds. It does not reach an answer built by an
exception handler (401 from the bearer guard, 404, the redacted 422 of a body
FastAPI rejects before any dependency runs). A middleware wraps ``send``, so it
sees every ``http.response.start`` whichever component produced it.

Pure ASGI rather than ``BaseHTTPMiddleware``: no body buffering, no task hop.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NO_STORE = "no-store"


class NoStoreMiddleware:
    """Sets ``Cache-Control: no-store`` on responses to ``prefix`` and below."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self._app = app
        self._prefix = prefix.rstrip("/")

    def _covers(self, path: str) -> bool:
        return path == self._prefix or path.startswith(self._prefix + "/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._covers(scope["path"]):
            await self._app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = NO_STORE
            await send(message)

        await self._app(scope, receive, send_no_store)
