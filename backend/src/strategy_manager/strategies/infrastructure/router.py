"""``/strategies`` — registering what this system will act on, and arming it.

Nothing here executes a trade or touches an exchange. It writes configuration
rows, and the worker reads them. The one thing it removes is a strategy that never
acted (``DELETE``, decision 42): a strategy with any history is refused and can
only be archived.

**Two things about this surface are deliberate and will look like omissions.**

There is no ``POST`` body field for ``enabled``: a newly registered strategy
is always off. Registering answers "is this configured correctly?" and arming
answers "should this trade now?", and only the second one moves money. They
are separate calls so that neither can be done by accident while doing the
other.

There is no way to change ``exchange``, ``venue`` or ``settlement_currency``
after registration. That is the guard, not a gap — ``UpdateStrategy`` explains why
at length. In short: it is not an edit, it is a different pool of money, and a
strategy switched between pools routes the close of an open position to the
wrong adapter.

``strategy_id`` is supplied by the caller and is the alert's ``signalType``
UUID. The webhook looks a strategy up under exactly that id, so an id chosen
here rather than copied from the alert would never match anything.
"""

import logging
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AfterValidator, BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.pool_sizing import SqlAlchemyPoolSizing
from strategy_manager.allocation.application.allocate_capital import UnknownPoolError
from strategy_manager.allocation.application.ports import PoolSizingPort
from strategy_manager.allocation.application.preview_share import PreviewShare, SharePreview
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.performance.domain.public_capital import public_capital
from strategy_manager.performance.infrastructure.public_strategies_source import (
    SqlAlchemyPublicStrategiesSource,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.leverage import (
    MAX_LEVERAGE,
    NEW_SEAT_LEVERAGE,
    Leverage,
    LeverageAboveStopCap,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Instant, Money
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.archive_strategy import (
    ArchiveStrategy,
    OpenPosition,
    StillEnabled,
)
from strategy_manager.strategies.application.code_entry import CheckInviteCode
from strategy_manager.strategies.application.delete_strategy import (
    DeleteStrategy,
    StrategyHasHistory,
)
from strategy_manager.strategies.application.invite_codes import (
    IssueInviteCode,
    ListInviteCodes,
    RevokeInviteCode,
    StrategyNotPrivate,
    UnknownInviteCode,
)
from strategy_manager.strategies.application.ports import (
    AuthorHasNoDisplayName,
    ListedCode,
    PairCatalogPort,
    SubscriberCounts,
)
from strategy_manager.strategies.application.regenerate_webhook_secret import (
    RegenerateWebhookSecret,
)
from strategy_manager.strategies.application.register_strategy import (
    PoolNotAvailable,
    RegisterCommand,
    RegisterStrategy,
    StrategyAlreadyRegistered,
)
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.application.subscriber_locks import SubscribersChanged
from strategy_manager.strategies.application.update_strategy import (
    UNCHANGED,
    StrategyArchived,
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.allowed_pairs import EmptyAllowedPairs
from strategy_manager.strategies.domain.description import description_of
from strategy_manager.strategies.domain.enablement import EnablementEvent, Uptime, uptime
from strategy_manager.strategies.domain.invite_code import (
    InviteCodeNotLive,
    TooManyCodeAttempts,
)
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
    PairsChangedConcurrently,
    UnknownPairs,
)
from strategy_manager.strategies.domain.share_token import link_opens
from strategy_manager.strategies.domain.stop_loss import StopLossPct
from strategy_manager.strategies.domain.strategy import (
    Entry,
    FillMode,
    Strategy,
    Visibility,
    offered_to,
)
from strategy_manager.strategies.infrastructure.author_names import SqlAlchemyAuthorNames
from strategy_manager.strategies.infrastructure.author_subscription_adapter import (
    SqlAlchemyAuthorSubscription,
)
from strategy_manager.strategies.infrastructure.code_entry_http import (
    CodeCheckDep,
    CodeQuery,
    LinkQuery,
    code_refusal,
)
from strategy_manager.strategies.infrastructure.enablement_log import (
    SqlAlchemyEnablementLog,
)
from strategy_manager.strategies.infrastructure.exposure_adapter import (
    StrategyExposureAdapter,
)
from strategy_manager.strategies.infrastructure.history_adapter import StrategyHistoryAdapter
from strategy_manager.strategies.infrastructure.invite_codes_adapter import SqlAlchemyInviteCodes
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from strategy_manager.strategies.infrastructure.pool_catalog import (
    SqlAlchemyPoolCatalog,
)
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import (
    AuthorStrategyRepository,
    SqlAlchemyStrategyRepository,
    is_name_conflict,
)
from strategy_manager.strategies.infrastructure.share_input import Share
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)
from strategy_manager.strategies.infrastructure.uptime_view import UptimeView
from strategy_manager.subscriptions.domain.subscription import Subscription
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)
from strategy_manager.subscriptions.infrastructure.router import SubscriptionView

# Authentication is attached to the ROUTER, so it applies to every route
# declared below AND to every route anyone adds after this line — without the
# author of that route doing, knowing or remembering anything. The protection
# is structural, not a checklist item.
#
# That distinction is the whole point. Per-endpoint dependencies protect the
# endpoints someone remembered, and this file is a place where endpoints get
# added: the next one added in a hurry is precisely the one that would ship
# open, and it would look exactly like the four already here. A decorator that
# has to be copied is a rule that will eventually not be.
#
# Any signed-in user may author (multi-user design AD8, decision 23), so the
# router asks for a signed-in user and not for the admin. Which strategies a route
# can reach is the repository's business: every route reads through
# ``AuthorStrategyRepository``, so another user's strategy is a 404.
#
# The router's dependency is what makes the protection structural; a route's own
# ``user`` parameter is only how it gets the user it needs, and resolves the same
# dependency once per request.
router = APIRouter(
    prefix="/strategies",
    tags=["strategies"],
    dependencies=[Depends(current_user)],
)

logger = logging.getLogger(__name__)

SHARE_PREVIEW_FAULT_DETAIL = "share preview data failed an integrity check"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(current_user)]



class StrategyView(BaseModel):
    """What a strategy looks like from outside. Deliberately flat: the
    ``policy`` value object is an internal grouping, not an API shape."""

    id: UUID
    name: str
    # The author's own words, plain text (decision 38), or null.
    description: str | None
    # Where its positions are stopped, as a percentage of price from the entry; it caps
    # every seat's leverage (subscriber-safety D5).
    stop_loss_pct: Money
    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    enabled: bool
    visibility: Visibility
    # The link's token while LINK, else null (decision 41). Only the author reads
    # this view, and the link is theirs to pass on.
    share_token: str | None
    archived_at: datetime | None
    allowed_pairs: list[str]
    uptime: UptimeView
    # The SIGNED-IN user's own ACTIVE or LEAVING subscription to this strategy, or
    # null (multi-user C.4b). The share lives there, not on the strategy.
    subscription: SubscriptionView | None
    # The last four characters of the strategy's current webhook secret, for the panel's
    # mask. Named without ``webhook_secret`` on purpose: that name is the issuing
    # routes' alone, and four characters are all this carries.
    secret_last4: str
    # The author's total (decisions 10 and 30): everyone with an ACTIVE subscription,
    # the author and simulated subscribers included, and how many of them trade it
    # live. ``live_subscribers`` and ``capital`` say what the public list says, on a
    # private strategy too, so under the brake they are 0 and null. No name, no e-mail
    # and no single seat's amount.
    subscribers: int
    live_subscribers: int
    capital: Money | None
    # When the strategy was registered, for My strategies' sort by age (tasks.md L.1).
    created_at: datetime | None

    @classmethod
    def of(
        cls,
        strategy: Strategy,
        uptime_value: Uptime,
        subscription: Subscription | None,
        secret_last4: str,
        counts: SubscriberCounts,
        capital: Decimal | None,
    ) -> "StrategyView":
        return cls(
            id=strategy.id,
            name=strategy.name,
            description=strategy.description,
            stop_loss_pct=strategy.stop_loss_pct.value,
            exchange=strategy.policy.exchange,
            venue=strategy.policy.venue,
            settlement_currency=strategy.policy.settlement_currency,
            fill_mode=strategy.policy.fill_mode,
            enabled=strategy.enabled,
            visibility=strategy.visibility,
            share_token=strategy.share_token,
            archived_at=strategy.archived_at,
            allowed_pairs=strategy.allowed_pairs.sorted(),
            uptime=UptimeView.of(uptime_value),
            subscription=None if subscription is None else SubscriptionView.of(subscription),
            secret_last4=secret_last4,
            subscribers=counts.subscribers,
            live_subscribers=counts.live,
            capital=capital,
            created_at=strategy.created_at,
        )


class RegisteredStrategyView(StrategyView):
    """The create response: the strategy and its webhook secret, shown ONCE. Only the
    hash is stored, so no read returns it again; a lost secret is regenerated."""

    webhook_secret: str


class WebhookSecretView(BaseModel):
    """The regenerate response: the new secret, shown once."""

    webhook_secret: str


class InviteCodeView(BaseModel):
    """A live invitation code in its author's list: no code, only its last four."""

    id: UUID
    hint: str
    expires_at: datetime

    @classmethod
    def of(cls, listed: ListedCode) -> "InviteCodeView":
        return cls(id=listed.id, hint=listed.hint, expires_at=listed.expires_at)


class IssuedInviteCodeView(InviteCodeView):
    """A code just made, shown once as ``XXXX-XXXX``: only its hash is stored."""

    code: str


# No answer carrying a secret or a code may be kept by the browser or an intermediary.
_NO_STORE = {"Cache-Control": "no-store"}


def _own(session: AsyncSession, user: User) -> AuthorStrategyRepository:
    """The signed-in user's strategies, and nobody else's: the only way a route here
    reads a strategy."""
    return AuthorStrategyRepository(session, user.id)


async def _view(
    session: AsyncSession, user: User, strategy: Strategy, events: list[EnablementEvent]
) -> StrategyView:
    """One strategy as ``user`` sees it: its uptime, the user's own subscription and
    the last four of its secret."""
    held = await SqlAlchemySubscriptionRepository(session).live_for_strategies(
        user.id, [strategy.id]
    )
    last4s = await _own(session, user).secret_last4s([strategy.id])
    counts = await _subscriber_counts(session, [strategy.id])
    capitals = await _capitals(session, [strategy.id])
    return StrategyView.of(
        strategy,
        uptime(events, datetime.now(UTC)),
        held.get(strategy.id),
        last4s[strategy.id],
        counts[strategy.id],
        capitals[strategy.id],
    )


class EnablementEventView(BaseModel):
    """One row of ``GET /strategies/{id}/events`` (design.md § 14)."""

    enabled: bool
    occurred_at: datetime
    origin: str

    @classmethod
    def of(cls, event: EnablementEvent) -> "EnablementEventView":
        return cls(enabled=event.enabled, occurred_at=event.occurred_at, origin=event.origin.value)


def _stored_description(value: str | None) -> str | None:
    try:
        return description_of(value)
    except InvariantViolation as exc:
        # A ``ValueError`` is what the 422 handler answers, with its fixed message.
        raise ValueError(str(exc)) from None


#: The author's description as the API takes it: a JSON string or null (pydantic
#: turns no number or list into a string), then put in its stored shape (trimmed, a
#: blank one made null) or refused with a 422.
Description = Annotated[str | None, AfterValidator(_stored_description)]

#: The author's seat's leverage as the API takes it: a JSON integer from 1 to the
#: cap, strict, as ``POST /api/subscriptions`` takes a subscriber's (decision 38).
LeverageInput = Annotated[int, Field(strict=True, ge=1, le=MAX_LEVERAGE)]


def _stop_level(value: Decimal) -> Decimal:
    try:
        return StopLossPct(value).value
    except InvariantViolation as exc:
        raise ValueError(str(exc)) from None


#: A stop level as the API takes it: a decimal from 1 to 50 percent of price with at most
#: two decimals, refused with a 422 naming the field otherwise. Checked by the domain's own
#: ``StopLossPct``, so the API and the database CHECK cannot drift apart.
StopLevel = Annotated[Decimal, AfterValidator(_stop_level)]


class RegisterRequest(BaseModel):
    """``id`` is the alert's ``signalType``. It is required, and there is no
    server-side default, because a generated one would match no alert."""

    id: UUID
    name: str = Field(min_length=1)
    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    # Typed by hand, never assumed (decision 39).
    allocation_percent: Share
    allowed_pairs: list[str] = Field(min_length=1)
    # Nothing turns public without the author's choice (decision 21).
    visibility: Visibility = Visibility.PRIVATE
    description: Description = None
    # The author's seat's, like the share above; it starts at 1x unless chosen.
    leverage: LeverageInput = NEW_SEAT_LEVERAGE.value
    # Required: a strategy is never registered without a level (D5). The form offers 10.
    stop_loss_pct: StopLevel


class UpdateRequest(BaseModel):
    """Every field is optional; omitted means unchanged.

    ``exchange``, ``venue`` and ``settlement_currency`` are absent on purpose
    — see this module's docstring.
    """

    name: str | None = Field(default=None, min_length=1)
    fill_mode: FillMode | None = None
    enabled: bool | None = None
    visibility: Visibility | None = None
    # Unlike the fields above, null here clears it; leaving it out keeps it.
    description: Description = None
    # Applies to openings made after the change only (D5); left out keeps it.
    stop_loss_pct: StopLevel | None = None
    # The share is each subscriber's now (``PATCH /api/subscriptions/{id}``). A body
    # that still carries one is refused, whatever its value, rather than accepted
    # and ignored: the validator below fires for any value present, ``null``
    # included, and never for the default. Only this field is refused; other
    # unknown keys are ignored as before.
    allocation_percent: object = Field(
        default=None,
        exclude=True,
        description="Refused: change a share through PATCH /api/subscriptions/{id}.",
    )

    @field_validator("allocation_percent", mode="before")
    @classmethod
    def _refuse_share(cls, value: object) -> object:
        raise ValueError("a strategy has no share; change it through its subscription")


class SharePreviewPoolBody(BaseModel):
    """The strategy's own pool, taken from the strategy row the path names."""

    exchange: Exchange
    venue: Venue
    settlement_currency: Currency


class SharePreviewBalanceBody(BaseModel):
    total: Money
    observed_at: Instant
    stale: bool


class SharePreviewExactBody(BaseModel):
    """``share`` is a plain decimal STRING in canonical form: it is whatever the
    caller can type, so it may have decimals."""

    share: str
    amount: Money
    #: ``amount`` times the leverage the caller asked about, null when none was
    #: asked: the panel shows it and never multiplies money itself (PR I, I.3).
    notional: Money | None
    below_pool_minimum: bool


class SharePreviewStepBody(BaseModel):
    """``share`` is a JSON integer, like a count: a step is a whole share."""

    share: int
    amount: Money
    below_pool_minimum: bool


class SharePreviewBody(BaseModel):
    """``balance``, ``exact`` and ``steps`` are null, null and empty together: a
    pool nothing has synced has no amount, never a zero. ``exact`` is also null
    when the caller holds no seat and asked no share (decision 39)."""

    strategy_id: UUID
    pool: SharePreviewPoolBody
    currency: Currency
    pool_minimum: Money
    balance: SharePreviewBalanceBody | None
    exact: SharePreviewExactBody | None
    steps: list[SharePreviewStepBody]

    @classmethod
    def of(
        cls, strategy_id: UUID, preview: SharePreview, leverage: Leverage | None = None
    ) -> "SharePreviewBody":
        balance = preview.balance
        exact = preview.exact
        return cls(
            strategy_id=strategy_id,
            pool=SharePreviewPoolBody(
                exchange=preview.pool.exchange,
                venue=preview.pool.venue,
                settlement_currency=preview.pool.settlement_currency,
            ),
            currency=preview.pool.settlement_currency,
            pool_minimum=preview.pool_minimum,
            balance=(
                None
                if balance is None
                else SharePreviewBalanceBody(
                    total=balance.total, observed_at=balance.observed_at, stale=balance.stale
                )
            ),
            exact=(
                None
                if exact is None
                else SharePreviewExactBody(
                    share=_canonical_share(exact.share),
                    amount=exact.amount,
                    notional=None if leverage is None else leverage.notional(exact.amount),
                    below_pool_minimum=exact.below_pool_minimum,
                )
            ),
            steps=[
                SharePreviewStepBody(
                    share=int(step.share),
                    amount=step.amount,
                    below_pool_minimum=step.below_pool_minimum,
                )
                for step in preview.steps
            ],
        )


def _canonical_share(share: Decimal) -> str:
    """``33.50`` is ``33.5`` and ``1E+1`` is ``10``: positional notation, no
    exponent and no trailing fractional zero. Done on the text of the exact value,
    not with ``normalize()``, which rounds to the context's 28 digits."""
    written = format(share, "f")
    return written.rstrip("0").rstrip(".") if "." in written else written


class ReplacePairsRequest(BaseModel):
    """``PUT /strategies/{id}/allowed-pairs`` -- the panel sends the
    COMPLETE list it wants; this replaces the whole column, never merges
    (design.md § 6)."""

    pairs: list[str] = Field(min_length=1)


PairCatalogDep = Annotated[PairCatalogPort, Depends(get_pair_catalog)]

# The error codes the panel decides on (design addendum § E). The body carries its
# own code, so a client never depends on the status alone.
UNKNOWN_PAIRS = "UNKNOWN_PAIRS"
PAIR_CATALOGUE_UNAVAILABLE = "PAIR_CATALOGUE_UNAVAILABLE"
PAIR_CATALOGUE_NOT_SERVED = "PAIR_CATALOGUE_NOT_SERVED"
PAIRS_CHANGED = "PAIRS_CHANGED"


def _pair_refusal(
    exc: UnknownPairs | PairCatalogNotServed | PairCatalogUnavailable | PairsChangedConcurrently,
) -> HTTPException:
    """The HTTP form of the four pair-catalogue refusals, shared by POST and PUT.

    The use case already logged one WARNING for each, so nothing is logged here.
    No venue payload, URL or credential is in any body: only the symbols the
    caller itself sent, normalized.
    """
    if isinstance(exc, UnknownPairs):
        # The input is the problem: the symbols are named, sorted.
        return HTTPException(
            status_code=422,
            detail={"error": UNKNOWN_PAIRS, "message": str(exc), "unknown": list(exc.unknown)},
        )
    if isinstance(exc, PairCatalogNotServed):
        # The request names a pool this system cannot validate pairs for.
        return HTTPException(
            status_code=422,
            detail={
                "error": PAIR_CATALOGUE_NOT_SERVED,
                "message": "pairs cannot be checked for this pool: no catalogue is served for it",
            },
        )
    if isinstance(exc, PairCatalogUnavailable):
        # The upstream venue failed: 502, not 422 (the operator's input was fine).
        return HTTPException(
            status_code=502,
            detail={
                "error": PAIR_CATALOGUE_UNAVAILABLE,
                "message": "the exchange's pair list could not be read, so nothing was saved; "
                "try again",
            },
        )
    # PairsChangedConcurrently: a well-formed request whose target changed under it.
    return HTTPException(status_code=409, detail={"error": PAIRS_CHANGED, "message": str(exc)})


def _no_display_name(exc: AuthorHasNoDisplayName) -> HTTPException:
    return HTTPException(
        status_code=409, detail={"error": "AUTHOR_HAS_NO_DISPLAY_NAME", "message": str(exc)}
    )


def get_register_strategy(session: SessionDep, pairs: PairCatalogDep) -> RegisterStrategy:
    """The real wiring. The catalogue comes from ``get_pair_catalog``, so a test
    overrides ONE dependency and no router test reaches a venue."""
    return RegisterStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pools=SqlAlchemyPoolCatalog(session),
        pairs=pairs,
        commit=session,
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
        author_subscriptions=SqlAlchemyAuthorSubscription(session),
        author_names=SqlAlchemyAuthorNames(session),
    )


def get_replace_allowed_pairs(
    session: SessionDep, user: CurrentUserDep, pairs: PairCatalogDep
) -> ReplaceAllowedPairs:
    return ReplaceAllowedPairs(repository=_own(session, user), pairs=pairs, commit=session)


def get_pool_sizing(session: SessionDep) -> PoolSizingPort:
    """The real read of a pool's minimum and snapshot. A test overrides ONE
    dependency to put a fake port in its place."""
    return SqlAlchemyPoolSizing(
        session, SystemClock(), get_settings().balance_snapshot_max_age_seconds
    )


def get_preview_share(sizing: Annotated[PoolSizingPort, Depends(get_pool_sizing)]) -> PreviewShare:
    return PreviewShare(sizing)


def _subscribers(session: AsyncSession) -> StrategySubscribersAdapter:
    ledger = SqlAlchemyLedgerRepository(session)
    return StrategySubscribersAdapter(session, ledger, ReadSymbolHoldings(ledger))


async def _subscriber_counts(
    session: AsyncSession, strategy_ids: Sequence[UUID]
) -> dict[UUID, SubscriberCounts]:
    """Each strategy's counts, in one statement whatever their number, and zero
    where nobody holds it. Under the brake nobody trades live, whatever their mode,
    so the live count says what the public list says."""
    found = await _subscribers(session).counts(strategy_ids)
    brake = get_settings().dry_run
    counts: dict[UUID, SubscriberCounts] = {}
    for strategy_id in strategy_ids:
        held = found.get(strategy_id, SubscriberCounts(0, 0))
        counts[strategy_id] = replace(held, live=0) if brake else held
    return counts


async def _capitals(
    session: AsyncSession, strategy_ids: Sequence[UUID]
) -> dict[UUID, Decimal | None]:
    """The one figure the public list shows (decisions 10 and 30), read the same way
    for a strategy that is not on it: its author is told what their private strategy
    holds too. Null under the brake, when nobody trades live."""
    if get_settings().dry_run:
        return dict.fromkeys(strategy_ids)
    seats = await SqlAlchemyPublicStrategiesSource(session).live_seats(strategy_ids)
    return {strategy_id: public_capital(seats.get(strategy_id, ())) for strategy_id in strategy_ids}


def get_delete_strategy(session: SessionDep, user: CurrentUserDep) -> DeleteStrategy:
    """The real wiring, the ``get_register_strategy`` pattern: a router test
    overrides this ONE dependency."""
    return DeleteStrategy(
        repository=_own(session, user),
        pool_lock=PoolLockAdapter(session),
        subscribers=_subscribers(session),
        history=StrategyHistoryAdapter(
            signals=SqlAlchemySignalRepository(session),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
            ledger=SqlAlchemyLedgerRepository(session),
            proposals=SqlAlchemyBookingProposalRepository(session),
            enablement_log=SqlAlchemyEnablementLog(session),
            session=session,
        ),
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
        commit=session,
    )


@router.post("", response_model=RegisteredStrategyView, status_code=201)
async def register_strategy(
    body: RegisterRequest,
    session: SessionDep,
    user: CurrentUserDep,
    use_case: Annotated[RegisterStrategy, Depends(get_register_strategy)],
    response: Response,
) -> RegisteredStrategyView:
    """The signed-in ``User`` is the author (multi-user design AD2), whoever they
    are: any signed-in user may author (AD8).

    The answer carries the strategy's webhook secret, the one time it is shown (AD6)."""
    try:
        registration = await use_case.register(
            RegisterCommand(
                strategy_id=body.id,
                name=body.name,
                exchange=body.exchange,
                venue=body.venue,
                settlement_currency=body.settlement_currency,
                fill_mode=body.fill_mode,
                allocation_percent=body.allocation_percent,
                allowed_pairs=body.allowed_pairs,
                author_id=user.id,
                stop_loss_pct=StopLossPct(body.stop_loss_pct),
                visibility=body.visibility,
                description=body.description,
                leverage=Leverage(body.leverage),
            )
        )
    except StrategyAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LeverageAboveStopCap as exc:
        # Nothing was written: the cap is asked before the strategy is.
        raise HTTPException(
            status_code=409, detail={"error": exc.reason_code, "message": str(exc)}
        ) from exc
    except PoolNotAvailable as exc:
        # May come after the strategy row was flushed (the author's pool deleted
        # since the check): the rollback leaves neither row and frees its locks.
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmptyAllowedPairs as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuthorHasNoDisplayName as exc:
        raise _no_display_name(exc) from exc
    except (UnknownPairs, PairCatalogNotServed, PairCatalogUnavailable) as exc:
        raise _pair_refusal(exc) from exc
    except IntegrityError as exc:
        # ``(author, name)`` is UNIQUE at the database level. Reported as a conflict
        # rather than a 500, because the caller can fix it by sending another
        # name. Only that constraint: any other integrity failure is a defect and
        # stays a 500, not a name clash the caller is told to fix. The text says
        # nothing of other users' strategies, whose names are not this caller's.
        if not is_name_conflict(exc):
            raise
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    # A just-created strategy has zero events by construction (creation
    # writes no event, F8) -- no query needed for its uptime.
    view = await _view(session, user, registration.strategy, [])
    response.headers.update(_NO_STORE)
    return RegisteredStrategyView(
        **view.model_dump(), webhook_secret=registration.webhook_secret
    )


@router.post("/{strategy_id}/webhook-secret", response_model=WebhookSecretView)
async def regenerate_webhook_secret(
    strategy_id: UUID,
    session: SessionDep,
    user: CurrentUserDep,
    response: Response,
) -> WebhookSecretView:
    """Replaces the strategy's secret and returns the new one, once. Only its author
    may (another user's strategy is a 404, AD8); an archived strategy is a 409. The
    old secret is refused at the webhook from the commit on."""
    use_case = RegenerateWebhookSecret(repository=_own(session, user), commit=session)
    try:
        secret = await use_case.regenerate(strategy_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    response.headers.update(_NO_STORE)
    return WebhookSecretView(webhook_secret=secret)


@router.post(
    "/{strategy_id}/invite-codes", response_model=IssuedInviteCodeView, status_code=201
)
async def issue_invite_code(
    strategy_id: UUID,
    session: SessionDep,
    user: CurrentUserDep,
    response: Response,
) -> IssuedInviteCodeView:
    """Makes a single-use code for one of the author's PRIVATE strategies (decision
    41), valid 7 days, and shows it this once. Another user's strategy is a 404."""
    use_case = IssueInviteCode(
        repository=_own(session, user),
        codes=SqlAlchemyInviteCodes(session),
        author_names=SqlAlchemyAuthorNames(session),
        commit=session,
        clock=SystemClock(),
    )
    try:
        issued = await use_case.issue(strategy_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    except StrategyNotPrivate as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_NOT_PRIVATE", "message": str(exc)}
        ) from exc
    except AuthorHasNoDisplayName as exc:
        raise _no_display_name(exc) from exc
    response.headers.update(_NO_STORE)
    return IssuedInviteCodeView(
        id=issued.id,
        code=issued.code.display,
        hint=issued.code.hint,
        expires_at=issued.expires_at,
    )


@router.get("/{strategy_id}/invite-codes", response_model=list[InviteCodeView])
async def list_invite_codes(
    strategy_id: UUID, session: SessionDep, user: CurrentUserDep
) -> list[InviteCodeView]:
    """The author's live codes for this strategy, oldest first, with no code in them."""
    use_case = ListInviteCodes(
        repository=_own(session, user), codes=SqlAlchemyInviteCodes(session), clock=SystemClock()
    )
    try:
        listed = await use_case.list(strategy_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [InviteCodeView.of(each) for each in listed]


@router.delete("/{strategy_id}/invite-codes/{code_id}", status_code=204)
async def revoke_invite_code(
    strategy_id: UUID, code_id: UUID, session: SessionDep, user: CurrentUserDep
) -> Response:
    """Revokes a live code of the author's strategy; its row is kept. A code that is
    not live, or not this strategy's, is a 404: there is nothing to revoke."""
    use_case = RevokeInviteCode(
        repository=_own(session, user),
        codes=SqlAlchemyInviteCodes(session),
        commit=session,
        clock=SystemClock(),
    )
    try:
        await use_case.revoke(strategy_id, code_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownInviteCode as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("", response_model=list[StrategyView])
async def list_strategies(
    session: SessionDep, user: CurrentUserDep, include_archived: bool = False
) -> list[StrategyView]:
    """The signed-in user's OWN strategies, the admin's included (AD8): another
    author's are not listed, public or not. Seeing other authors' strategies is the
    public list's job (PR F). Each carries the signed-in user's own subscription to
    it, from one query."""
    strategies = await _own(session, user).list_all(include_archived=include_archived)
    # ONE query for every strategy's events (design.md § 14:
    # "list_all(include_archived) + one events query -> uptime()"), not one
    # per strategy -- acceptable either way at today's scale (tens of
    # strategies), but this is the bulk form.
    events_by_strategy = await SqlAlchemyEnablementLog(session).list_for_many(
        [strategy.id for strategy in strategies]
    )
    held = await SqlAlchemySubscriptionRepository(session).live_for_strategies(
        user.id, [strategy.id for strategy in strategies]
    )
    last4s = await _own(session, user).secret_last4s([strategy.id for strategy in strategies])
    counts = await _subscriber_counts(session, [strategy.id for strategy in strategies])
    capitals = await _capitals(session, [strategy.id for strategy in strategies])
    now = datetime.now(UTC)
    return [
        StrategyView.of(
            strategy,
            uptime(events_by_strategy.get(strategy.id, []), now),
            held.get(strategy.id),
            last4s[strategy.id],
            counts[strategy.id],
            capitals[strategy.id],
        )
        for strategy in strategies
    ]


@router.get("/{strategy_id}", response_model=StrategyView)
async def get_strategy(
    strategy_id: UUID, session: SessionDep, user: CurrentUserDep
) -> StrategyView:
    strategy = await _own(session, user).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return await _view(session, user, strategy, events)


@router.get("/{strategy_id}/events", response_model=list[EnablementEventView])
async def get_strategy_events(
    strategy_id: UUID, session: SessionDep, user: CurrentUserDep
) -> list[EnablementEventView]:
    strategy = await _own(session, user).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return [EnablementEventView.of(event) for event in events]


async def _reaches_preview(
    session: AsyncSession,
    strategy: Strategy,
    user: User,
    subscription: Subscription | None,
    entry: tuple[str | None, str | None, CheckInviteCode],
) -> bool:
    """Who the preview answers: the author, whoever holds a live subscription, which
    outlasts a turn to private (decision 21), and anyone who may subscribe, with the
    link or the code they bring (decision 41). Every figure in it is from the reader's
    own pool, and the market is on the public page. The code is read only when nothing
    else opens the strategy; a dead one or the limit is refused."""
    if strategy.author_id == user.id or subscription is not None:
        return True
    if strategy.archived_at is not None:
        return False
    author_named = await SqlAlchemyAuthorNames(session).has_display_name(strategy.author_id)
    link, code, codes = entry
    by_link = Entry.LINK if link_opens(strategy.share_token, link) else Entry.NONE
    if offered_to(strategy.visibility, author_named=author_named, entry=by_link):
        return True
    if code is None or not offered_to(
        strategy.visibility, author_named=author_named, entry=Entry.CODE
    ):
        return False
    try:
        return await codes.check(user.id, strategy.id, code) is not None
    except (TooManyCodeAttempts, InviteCodeNotLive) as exc:
        raise code_refusal(exc) from exc


@router.get("/{strategy_id}/share-preview", response_model=SharePreviewBody)
async def preview_share(
    strategy_id: UUID,
    session: SessionDep,
    user: CurrentUserDep,
    use_case: Annotated[PreviewShare, Depends(get_preview_share)],
    codes: CodeCheckDep,
    share: Annotated[Share | None, Query()] = None,
    leverage: Annotated[int | None, Query(ge=1, le=MAX_LEVERAGE)] = None,
    link: LinkQuery = None,
    code: CodeQuery = None,
) -> SharePreviewBody:
    """What a share of this strategy's pool would ask for (design addendum "unit
    12f", sections C2 and H). It reads the strategy and then the pool's row and
    snapshot, and calls no exchange. The API process decrypts nothing and this route
    needs no key. It writes only when the strategy opens to the reader by nothing but
    a code (decision 41): the code check takes the reader's attempts lock and, for a
    wrong or dead code, commits one failed attempt, on a connection of its own.

    The pool and the default share come from the strategy row the PATH names, never
    from the request: the inputs are the optional ``share``, bounded to
    ``0 < share <= 100``, and the optional ``leverage``, 1 to ``MAX_LEVERAGE``, which
    only adds the notional to ``exact``. Either out of range is refused with the
    application's 422 that echoes no input.

    A pool with no row is a fault in stored data (a strategy cannot be registered on
    one): one ERROR naming the strategy and the pool, and a fixed 500. A pool with
    no snapshot, or a stale one, is a normal answer and logs nothing.
    """
    strategy = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    held = await SqlAlchemySubscriptionRepository(session).live_for_strategies(
        user.id, [strategy_id]
    )
    subscription = held.get(strategy_id)
    if strategy is None or not await _reaches_preview(
        session, strategy, user, subscription, (link, code, codes)
    ):
        raise HTTPException(status_code=404, detail="no such strategy")
    policy = strategy.policy
    pool = PoolKey(policy.exchange, policy.venue, policy.settlement_currency)
    # No ``share`` asked: the signed-in user's own subscription's share, since that
    # is what sizes their next opening (tasks.md C.6). A user who holds none has no
    # share to size, so none is assumed and ``exact`` is null (decision 39).
    previewed = share
    if previewed is None and subscription is not None:
        previewed = subscription.allocation_percent.value
    try:
        # The SIGNED-IN user's own pool on the strategy's market (C.4b): a share is
        # a part of the subscriber's pool, so another user previews against theirs,
        # not the author's.
        preview = await use_case.preview(user.id, pool, previewed)
    except UnknownPoolError as exc:
        # Anyone signed in can ask about a public strategy, so a pool that is not
        # there is no fault of theirs, and no line for the operator.
        if strategy.author_id != user.id:
            raise HTTPException(status_code=404, detail="no such pool") from exc
        logger.error("share preview refused for strategy %s: %s", strategy_id, exc)
        raise HTTPException(status_code=500, detail=SHARE_PREVIEW_FAULT_DETAIL) from exc
    return SharePreviewBody.of(
        strategy.id, preview, None if leverage is None else Leverage(leverage)
    )


@router.put("/{strategy_id}/allowed-pairs", response_model=StrategyView)
async def replace_allowed_pairs(
    strategy_id: UUID,
    body: ReplacePairsRequest,
    session: SessionDep,
    user: CurrentUserDep,
    use_case: Annotated[ReplaceAllowedPairs, Depends(get_replace_allowed_pairs)],
) -> StrategyView:
    try:
        strategy = await use_case.replace(
            ReplaceAllowedPairsCommand(strategy_id=strategy_id, pairs=body.pairs)
        )
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    except EmptyAllowedPairs as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        UnknownPairs,
        PairCatalogNotServed,
        PairCatalogUnavailable,
        PairsChangedConcurrently,
    ) as exc:
        raise _pair_refusal(exc) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return await _view(session, user, strategy, events)


@router.patch("/{strategy_id}", response_model=StrategyView)
async def update_strategy(
    strategy_id: UUID, body: UpdateRequest, session: SessionDep, user: CurrentUserDep
) -> StrategyView:
    use_case = UpdateStrategy(
        repository=_own(session, user),
        commit=session,
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
        author_names=SqlAlchemyAuthorNames(session),
    )
    try:
        strategy = await use_case.update(
            UpdateCommand(
                strategy_id=strategy_id,
                name=body.name,
                fill_mode=body.fill_mode,
                enabled=body.enabled,
                visibility=body.visibility,
                stop_loss_pct=(
                    None if body.stop_loss_pct is None else StopLossPct(body.stop_loss_pct)
                ),
                # Sent, null included, is a change; left out is not.
                description=(
                    body.description if "description" in body.model_fields_set else UNCHANGED
                ),
            )
        )
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    except AuthorHasNoDisplayName as exc:
        raise _no_display_name(exc) from exc
    except IntegrityError as exc:
        if not is_name_conflict(exc):
            raise
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return await _view(session, user, strategy, events)


@router.post("/{strategy_id}/archive", response_model=StrategyView)
async def archive_strategy(
    strategy_id: UUID, session: SessionDep, user: CurrentUserDep
) -> StrategyView:
    """Decision 14: archive only a disabled, flat strategy. Idempotent --
    calling this again on an already-archived strategy answers 200 with the
    SAME ``archived_at``, never a fresh one (design.md § 8's sequence
    diagram; design.md's API table)."""
    use_case = ArchiveStrategy(
        repository=_own(session, user),
        pool_lock=PoolLockAdapter(session),
        subscribers=_subscribers(session),
        exposure=StrategyExposureAdapter(
            ledger=SqlAlchemyLedgerRepository(session),
            symbol_holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,
        clock=SystemClock(),
    )
    try:
        result = await use_case.archive(strategy_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StillEnabled as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STILL_ENABLED", "message": str(exc)}
        ) from exc
    except SubscribersChanged as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "SUBSCRIBERS_CHANGED", "message": str(exc)}
        ) from exc
    except OpenPosition as exc:
        # ``HTTPException.detail`` is serialized by Starlette's plain
        # ``json.dumps``, not ``jsonable_encoder`` -- a raw ``UUID`` in the
        # dict raises ``TypeError`` at response-render time, well after this
        # handler returns, so every id is stringified explicitly here.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "OPEN_POSITION",
                "message": str(exc),
                "symbols": sorted(exc.exposure.symbols),
                "allocations": [str(a) for a in exc.exposure.allocations],
                "live_reservations": [str(r) for r in exc.exposure.live_reservations],
                "in_flight_attempts": [str(a) for a in exc.exposure.in_flight_attempts],
            },
        ) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return await _view(session, user, result.strategy, events)


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: UUID,
    session: SessionDep,
    use_case: Annotated[DeleteStrategy, Depends(get_delete_strategy)],
) -> Response:
    """Decision 42: delete a strategy that never acted. Hard delete, answered 204
    with no body (there is no strategy left to describe). A repeated delete is a
    404, never a 204, so a wrong id is not hidden.

    Every refusal rolls the session back. The use case raises without rolling
    back, so the pool advisory lock and the strategy row lock would otherwise be
    held until the session closes, and a refusal by the database (a foreign key
    the count missed) leaves the transaction aborted for whoever uses the session
    next. The use case already logged one line for each outcome, so nothing is
    logged here (design addendum 9x, § F and § I).
    """
    try:
        await use_case.delete(strategy_id)
    except UnknownStrategy as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StillEnabled as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "STILL_ENABLED", "message": str(exc)}
        ) from exc
    except SubscribersChanged as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "SUBSCRIBERS_CHANGED", "message": str(exc)}
        ) from exc
    except StrategyHasHistory as exc:
        await session.rollback()
        # All six counts, always, as integers (counts, not money): a fixed shape
        # the panel renders without guessing which key is absent. A refusal by the
        # database carries the counts as read, and its message names the constraint.
        raise HTTPException(
            status_code=409,
            detail={"error": "HAS_HISTORY", "message": str(exc), "history": asdict(exc.history)},
        ) from exc
    return Response(status_code=204)
