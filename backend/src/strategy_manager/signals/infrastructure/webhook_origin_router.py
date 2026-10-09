"""``GET /webhook-origin``: the origin TradingView posts to (design.md, unit 12f
addendum, section F; spec: admin-api "The Webhook's Origin Is Served By Its Own
Route").

The webhook does NOT live on the panel's origin (decision 5): the panel and the
admin API are behind one tunnel and the webhook behind another host, so the
panel cannot work its full URL out of ``window.location``. This route tells it.

- **Body**: ``{"origin": "https://example.org"}`` or ``{"origin": null}``.
  ``null`` means "no usable value": unset and malformed read the same to the
  panel. Only the startup line (``webhook_origin_check``) tells them apart,
  which is why a malformed value is an ERROR there.
- **Bearer auth on the router**, as on every ``/api`` router. FastAPI does not
  re-apply a parent's dependencies to a bare router, so it is declared here.
- **The body never carries the webhook secret.** The route reads one setting,
  ``webhook_public_origin``, through the pure ``parse_webhook_origin``.
- **A malformed value never fails the request.** It is served as ``null``.
- No use case and no port: the route reads a setting through a pure function, as
  ``webhook_secret_router`` reads its own.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.signals.domain.webhook_origin import (
    InvalidWebhookOrigin,
    parse_webhook_origin,
)

router = APIRouter(
    prefix="/webhook-origin",
    tags=["webhook-origin"],
    dependencies=[Depends(require_admin_token)],
)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class WebhookOriginBody(BaseModel):
    origin: str | None


@router.get("", response_model=WebhookOriginBody)
async def read_webhook_origin(settings: SettingsDep) -> WebhookOriginBody:
    try:
        origin = parse_webhook_origin(settings.webhook_public_origin)
    except InvalidWebhookOrigin:
        origin = None
    return WebhookOriginBody(origin=origin)
