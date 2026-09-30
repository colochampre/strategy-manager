"""``PUT`` and ``DELETE /credentials/{exchange}`` and ``GET /credentials`` (design 8a § C,
§ H; design § 4b).

**The API never decrypts (decision 5).** ``PUT`` builds ``SaveCredential`` over
``CredentialWriterPort``, which has no ``load``, so a decrypt from this router
is a type error. ``GET`` reads the snapshot columns only, through a query that
names none of the columns that hold a secret. Neither route ever re-queries a
venue for a stored key.

**What a response may hold.** The last four characters of the key and the facts
recorded about it. Not the key, not the secret, not a raw permission payload,
not a ``permissions`` field. A refusal names tokens or fields in ``detail``,
never a payload.

**One body for every refusal:** ``{outcome, detail, missing?}``. The status says
whose problem it is:

- 422: the key, or the request, cannot be stored as sent. The owner fixes it.
- 502: the venue could not be reached. Nothing is wrong with the key as far as
  is known; retry by hand.
- 409: another save for the exchange won the race. Look before saving again.
- 404: no inspector serves the exchange (Pionex has none, design § J Q3).

``DELETE`` answers 404 for an exchange outside ``KNOWN_FUTURES_POOLS`` (owner
decision 31, the same as the PUT) before anything is locked or read, 404 when the
exchange has no active credential, 409 ``EXCHANGE_NOT_FLAT`` while the pool holds
exposure, and 200 with the exchange's ``EMPTY`` entry on success. It never needs
the master key, so an unusable one does not turn it into a 503.

The body itself is validated by pydantic before any of this runs, and a body
that fails is answered by ``redacted_validation_handler``, which never echoes a
submitted value. The confirmation times are the server's: ``extra="forbid"``
means a client that sends one is refused rather than ignored.

Authentication is attached to the ROUTER, like every ``/api`` router.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, Secret, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.application.delete_credential import (
    DeleteCredential,
    ExchangeNotFlat,
    ExchangeNotServed,
    NoActiveCredential,
)
from strategy_manager.accounts.application.save_credential import (
    SaveCredential,
    Saved,
    SaveOutcome,
    SaveRefused,
)
from strategy_manager.accounts.domain.credential_overview import CredentialOverview
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations, UnservedExchange
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_listing import (
    SqlAlchemyCredentialListing,
)
from strategy_manager.accounts.infrastructure.credential_revoker import (
    SqlAlchemyCredentialRevoker,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.key_inspectors.registry import KeyInspectorRegistry
from strategy_manager.accounts.infrastructure.pool_exposure_adapter import PoolExposureAdapter
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.wire import Instant
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_LABEL = "default"

#: A venue key or secret is printable ASCII with no whitespace (``!`` to ``~``).
#: httpx encodes a header value as ASCII, so anything else would crash the
#: inspector (a 500 with only a traceback in the log), and a control character
#: would be read as a different failure. Declarative on purpose: pydantic's own
#: message for a failed pattern never quotes the value. The engine's ``$`` does
#: not match before a trailing newline, so ``"KEY\n"`` fails too.
PRINTABLE_ASCII = r"^[\x21-\x7E]+$"
MAX_TOKEN_LENGTH = 256

#: Every refusal the use case can answer, and the status it becomes. ``SAVED`` is
#: the only success and is not here. A test pins that this covers every outcome,
#: so a ninth outcome cannot be added and fall through to a default.
OUTCOME_STATUS: dict[SaveOutcome, int] = {
    SaveOutcome.KEY_REJECTED: 422,
    SaveOutcome.WITHDRAW_PERMISSION: 422,
    SaveOutcome.PERMISSIONS_UNAVAILABLE: 422,
    SaveOutcome.CONFIRMATION_REQUIRED: 422,
    SaveOutcome.CONFIRMATION_NOT_APPLICABLE: 422,
    SaveOutcome.VENUE_UNREACHABLE: 502,
    SaveOutcome.CONCURRENT_SAVE: 409,
}


def get_save_credential(session: SessionDep) -> SaveCredential:
    """The real wiring: the live venue inspectors and the vault.

    An unusable master key is a deployment fault, not a fact about this request,
    so it answers 503 and logs one ERROR (which reaches Telegram through the
    alert bridge). Nothing about the key is in the message.
    """
    settings = get_settings()
    try:
        cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    except InvariantViolation as exc:
        logger.error("cannot save a credential: %s", exc)
        raise HTTPException(
            status_code=503, detail="credential storage is not configured"
        ) from None

    clock = SystemClock()
    return SaveCredential(
        KeyInspectorRegistry.for_settings(settings, clock),
        SqlAlchemyCredentialVault(session, cipher, clock),
        SqlAlchemyCapitalPoolWriter(session),
        session,
        clock,
    )


SaveCredentialDep = Annotated[SaveCredential, Depends(get_save_credential)]


def get_delete_credential(session: SessionDep) -> DeleteCredential:
    """The real wiring: every part over the request's ONE session, so the
    deactivation, the pool write and the commit are one transaction, and the pool
    lock and the row lock live and die with it.

    No cipher: deleting a key never opens it, so an unusable master key is not a
    reason to refuse (unlike ``get_save_credential``).
    """
    return DeleteCredential(
        SqlAlchemyCredentialRevoker(session, SystemClock()),
        PoolLockAdapter(session),
        PoolExposureAdapter.over(session),
        SqlAlchemyCapitalPoolWriter(session),
        session,
    )


DeleteCredentialDep = Annotated[DeleteCredential, Depends(get_delete_credential)]


class CredentialBody(BaseModel):
    """``extra="forbid"``: a client cannot supply a confirmation time or a fact."""

    model_config = ConfigDict(extra="forbid")

    api_key: Annotated[
        str,
        StringConstraints(min_length=4, max_length=MAX_TOKEN_LENGTH, pattern=PRINTABLE_ASCII),
    ]
    # ``SecretStr`` cannot carry a pattern; ``Secret[...]`` validates the inner
    # type and masks the same way (``repr`` shows ``**********``).
    api_secret: Secret[
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=MAX_TOKEN_LENGTH, pattern=PRINTABLE_ASCII),
        ]
    ]
    label: str = Field(default=DEFAULT_LABEL, min_length=1, max_length=64)
    withdrawals_disabled_confirmed: bool = False
    futures_enabled_confirmed: bool = False


class FactsBody(BaseModel):
    validated_at: Instant | None
    trade_capable: bool
    trade_capability_source: str
    trade_confirmed_at: Instant | None
    withdraw_check: str
    withdraw_confirmed_at: Instant | None
    internal_transfer: bool | None

    @classmethod
    def of(cls, facts: KeyFacts) -> "FactsBody":
        return cls(
            validated_at=facts.validated_at,
            trade_capable=facts.trade_capable,
            trade_capability_source=facts.trade_capability_source.value,
            trade_confirmed_at=facts.trade_confirmed_at,
            withdraw_check=facts.withdraw_check.value,
            withdraw_confirmed_at=facts.withdraw_confirmed_at,
            internal_transfer=facts.internal_transfer,
        )


class SavedBody(BaseModel):
    last4: str
    facts: FactsBody
    warnings: list[str]


class RefusalBody(BaseModel):
    """``missing`` is present only for ``CONFIRMATION_REQUIRED``."""

    outcome: SaveOutcome
    detail: str
    missing: list[str] | None = None


class CredentialEntry(BaseModel):
    """One exchange. ``EMPTY`` nulls everything after ``status``."""

    exchange: str
    status: Literal["STORED", "EMPTY"]
    last4: str | None
    label: str | None
    stored_at: Instant | None
    validated_at: Instant | None
    trade_capable: bool | None
    trade_capability_source: str | None
    trade_confirmed_at: Instant | None
    withdraw_check: str | None
    withdraw_confirmed_at: Instant | None
    internal_transfer: bool | None

    @classmethod
    def of(cls, overview: CredentialOverview) -> "CredentialEntry":
        key = overview.key
        if key is None:
            return cls(
                exchange=overview.exchange,
                status="EMPTY",
                last4=None,
                label=None,
                stored_at=None,
                validated_at=None,
                trade_capable=None,
                trade_capability_source=None,
                trade_confirmed_at=None,
                withdraw_check=None,
                withdraw_confirmed_at=None,
                internal_transfer=None,
            )
        facts = key.facts
        return cls(
            exchange=overview.exchange,
            status="STORED",
            last4=key.last4,
            label=key.label,
            stored_at=key.stored_at,
            validated_at=facts.validated_at,
            trade_capable=facts.trade_capable,
            trade_capability_source=facts.trade_capability_source.value,
            trade_confirmed_at=facts.trade_confirmed_at,
            withdraw_check=facts.withdraw_check.value,
            withdraw_confirmed_at=facts.withdraw_confirmed_at,
            internal_transfer=facts.internal_transfer,
        )


class EnabledStrategyBody(BaseModel):
    id: str
    name: str


class NotFlatBody(BaseModel):
    """The 409 body: what blocks the deletion, each kind on its own list so the
    panel can say what is missing. Ids and names only; never a key."""

    outcome: Literal["EXCHANGE_NOT_FLAT"] = "EXCHANGE_NOT_FLAT"
    detail: str
    enabled_strategies: list[EnabledStrategyBody]
    symbols: list[str]
    allocations: list[str]
    live_reservations: list[str]
    in_flight_attempts: list[str]


def _refusal(result: SaveRefused) -> JSONResponse:
    body = RefusalBody(
        outcome=result.outcome,
        detail=result.detail,
        missing=list(result.missing) if result.missing else None,
    )
    return JSONResponse(
        status_code=OUTCOME_STATUS[result.outcome],
        content=body.model_dump(mode="json", exclude_none=True),
    )


@router.put(
    "/{exchange}",
    response_model=SavedBody,
    responses={
        404: {"description": "No inspector serves this exchange."},
        409: {"model": RefusalBody},
        422: {"model": RefusalBody},
        502: {"model": RefusalBody},
        503: {"description": "The master encryption key is unusable."},
    },
)
async def put_credential(
    exchange: str, body: CredentialBody, use_case: SaveCredentialDep
) -> SavedBody | JSONResponse:
    credential = ExchangeCredential(
        exchange=exchange,
        label=body.label,
        api_key=body.api_key,
        api_secret=body.api_secret.get_secret_value(),
    )
    confirmations = OwnerConfirmations(
        withdrawals_disabled=body.withdrawals_disabled_confirmed,
        futures_enabled=body.futures_enabled_confirmed,
    )
    try:
        result = await use_case.execute(credential, confirmations)
    except UnservedExchange:
        raise HTTPException(
            status_code=404, detail=f"exchange {exchange!r} is not served by this panel"
        ) from None

    if isinstance(result, Saved):
        return SavedBody(
            last4=result.last4,
            facts=FactsBody.of(result.facts),
            warnings=list(result.warnings),
        )
    return _refusal(result)


@router.get("", response_model=list[CredentialEntry])
async def list_credentials(session: SessionDep) -> list[CredentialEntry]:
    overviews = await SqlAlchemyCredentialListing(session).list_overview()
    return [CredentialEntry.of(overview) for overview in overviews]


@router.delete(
    "/{exchange}",
    response_model=CredentialEntry,
    responses={
        404: {"description": "The exchange is not served, or has no active credential."},
        409: {"model": NotFlatBody},
    },
)
async def delete_credential(
    exchange: str, use_case: DeleteCredentialDep
) -> CredentialEntry | JSONResponse:
    try:
        await use_case.execute(exchange)
    except ExchangeNotServed:
        # Owner decision 31: no lock, no read, no write happened.
        raise HTTPException(
            status_code=404, detail=f"exchange {exchange!r} is not served by this panel"
        ) from None
    except NoActiveCredential:
        raise HTTPException(
            status_code=404, detail=f"no active credential for exchange {exchange!r}"
        ) from None
    except ExchangeNotFlat as refusal:
        exposure = refusal.exposure
        body = NotFlatBody(
            detail=f"exchange {exchange!r} is not flat; see what is listed",
            enabled_strategies=[
                EnabledStrategyBody(id=str(s.id), name=s.name) for s in exposure.enabled_strategies
            ],
            symbols=sorted(exposure.symbols),
            allocations=[str(a) for a in exposure.allocations],
            live_reservations=[str(r) for r in exposure.live_reservations],
            in_flight_attempts=[str(a) for a in exposure.in_flight_attempts],
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))
    # The same shape an exchange that was never keyed already answers.
    return CredentialEntry.of(CredentialOverview(exchange=exchange, key=None))
