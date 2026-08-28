"""``POST /webhook/tradingview`` — the sole entry point for strategy signals.

Persistence and enqueue are the only side effects; no trade is ever executed
within this request/response cycle (spec: signal-ingress § Fast Enqueue-Only
Response). TradingView cannot sign its requests, so the shared secret travels
as a query parameter on the configured webhook URL (the alert body itself is
fixed — see design.md § "Alert Contract and Signal Routing").

The secret stays in the URL rather than moving into the body because the body
is persisted verbatim into ``signals.raw_payload``; ``access_log.py`` carries
the reasoning and keeps the value out of the access log.

Which address the allowlist judges depends on deployment, so this reads both
candidates and lets ``resolve_source_ip`` decide — it must never be decided
here by whichever value happens to be present.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.signals.application.ingest_signal import (
    IngestCommand,
    IngestSignal,
    MissingIdempotencyKeyError,
)
from strategy_manager.signals.domain.alert import (
    AlertParsingError,
    TradingViewAlert,
    derive_idempotency_key,
)
from strategy_manager.signals.infrastructure.auth import (
    CLOUDFLARE_CLIENT_IP_HEADER,
    SourceIpAndSecretAuth,
    resolve_source_ip,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository

router = APIRouter()


class WebhookResponse(BaseModel):
    signal_id: UUID
    accepted: bool
    duplicate: bool


@router.post("/webhook/tradingview", response_model=WebhookResponse)
async def receive_tradingview_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    secret: str | None = Query(default=None),
) -> WebhookResponse:
    source_ip = resolve_source_ip(
        peer_ip=request.client.host if request.client is not None else None,
        forwarded_ip=request.headers.get(CLOUDFLARE_CLIENT_IP_HEADER),
        behind_cloudflare_tunnel=settings.behind_cloudflare_tunnel,
    )
    auth = SourceIpAndSecretAuth.from_settings(settings)
    if not auth.authenticate(source_ip, secret):
        raise HTTPException(status_code=401, detail="unauthorized")

    body = await request.json()
    try:
        alert = TradingViewAlert.from_payload(body)
    except AlertParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        strategy_id = UUID(alert.signal_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="signal_type is not a valid UUID") from exc

    command = IngestCommand(
        strategy_id=strategy_id,
        idempotency_key=derive_idempotency_key(alert),
        action=alert.action,
        contracts=alert.contracts,
        position_size=alert.position_size,
        price=alert.price,
        symbol=alert.symbol,
        signal_type=alert.signal_type,
        raw_payload=body,
    )

    use_case = IngestSignal(
        repository=SqlAlchemySignalRepository(session),
        job_queue=PostgresJobQueue(session),
        uow=session,
    )
    try:
        result = await use_case.ingest(command)
    except MissingIdempotencyKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return WebhookResponse(
        signal_id=result.signal_id, accepted=True, duplicate=result.duplicate
    )
