"""``GET /webhook-secret``: the webhook shared secret, on explicit request only
(owner decision 23; design.md section 14).

This is the ONLY place ``settings.webhook_secret`` is ever returned. The panel
calls it when the operator clicks "Show secret", never on page load, and no
other payload of any route (a strategy, a credential, a list, a detail) carries
the value. ``tests/signals/infrastructure/test_webhook_secret_router.py`` walks
the application's own route table to keep that true for routes not yet written.

What keeps the value from leaking, beyond returning it once:

- **Bearer auth** on the router, exactly as on every other ``/api`` router.
- **``Cache-Control: no-store``** on the answer, so neither the browser nor an
  intermediary keeps a copy. ``Pragma: no-cache`` is not added: the spec asks
  for ``Cache-Control: no-store`` alone, and ``Pragma`` only matters to HTTP/1.0
  caches.
- **It is never logged.** Nothing here logs, no exception message here carries
  the value, and it is read only when the response is built. It is in the body,
  not the URL, so the access log's request line never holds it.
- **An unconfigured secret is not a secret.** ``""`` is refused with a 503 that
  names no value, never handed to a client as if it were one. Startup invariant
  3 already refuses to boot without one, so this is the defensive branch for a
  process whose setting was emptied afterwards.

The setting is a plain ``str`` (``Settings.webhook_secret``), not a
``SecretStr``, because ``signals/infrastructure/auth.py`` compares against it
directly.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token

router = APIRouter(
    prefix="/webhook-secret",
    tags=["webhook-secret"],
    dependencies=[Depends(require_admin_token)],
)

_NO_STORE = {"Cache-Control": "no-store"}

SettingsDep = Annotated[Settings, Depends(get_settings)]


class WebhookSecretBody(BaseModel):
    secret: str


@router.get("", response_model=WebhookSecretBody)
async def reveal_webhook_secret(
    settings: SettingsDep, response: Response
) -> WebhookSecretBody:
    if not settings.webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="the webhook secret is not configured",
            headers=_NO_STORE,
        )
    response.headers.update(_NO_STORE)
    return WebhookSecretBody(secret=settings.webhook_secret)
