"""One ``RequestValidationError`` handler for the whole application (6b.5).

FastAPI's default answer to a body that fails validation lists, per error, the
``input`` that failed and a ``ctx`` that can carry the validator's own
exception. For ``PUT /api/credentials/{exchange}`` the input is an API key and
its secret: a mistyped field would write the secret into the 422, and from
there into any proxy, browser devtools or error tracker on the way back to the
operator.

This handler answers the same status and the same ``detail`` list, but each
error is reduced to ``type``, ``loc`` and ``msg``:

- ``input`` and ``ctx`` are dropped, unconditionally. They are the two fields
  that hold submitted values.
- ``msg`` is pydantic's own text for the failed rule ("Field required",
  "Input should be a valid string"), which never quotes the input. The one
  exception is a custom validator: its ``ValueError`` (or failed ``assert``)
  text is written by whoever wrote the validator and may well interpolate the
  value, so for those two error types the message is replaced by a fixed one.
  The ``loc`` and ``type`` still say which field and which kind of mistake.

It is installed once, on the application, and not per router: a router that
forgot it would echo, and this project's silent-failure defects have all been
the thing somebody forgot.

**It logs nothing.** A 422 is the client's mistake, and the two things a log
line could carry (the errors and the request) are exactly what must not leave
the response. The access log already records the request line, and a body is
never part of it.
"""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

#: Error types whose ``msg`` is text a developer wrote and may quote the value.
_AUTHORED_MESSAGE_TYPES = frozenset({"value_error", "assertion_error"})
_GENERIC_MESSAGE = "Invalid value"


def _redact(error: Any) -> dict[str, Any]:
    kind = error.get("type")
    return {
        "type": kind,
        "loc": list(error.get("loc", ())),
        "msg": _GENERIC_MESSAGE if kind in _AUTHORED_MESSAGE_TYPES else error.get("msg"),
    }


async def redacted_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    # Starlette types every handler as taking ``Exception``; it only ever calls
    # this one for a ``RequestValidationError``. Anything else is not ours.
    if not isinstance(exc, RequestValidationError):
        raise exc
    return JSONResponse(
        status_code=422,
        content={"detail": [_redact(error) for error in exc.errors()]},
    )
