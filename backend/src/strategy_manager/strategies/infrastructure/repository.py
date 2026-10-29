"""SQLAlchemy implementation of ``StrategyRepositoryPort``."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.ports import StrategyStillReferenced
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs
from strategy_manager.strategies.domain.strategy import (
    AllocationPolicy,
    FillMode,
    Strategy,
    Visibility,
)
from strategy_manager.strategies.infrastructure.models import StrategyRow

FOREIGN_KEY_VIOLATION = "23503"
"""PostgreSQL's SQLSTATE for ``foreign_key_violation``."""

AUTHOR_NAME_CONSTRAINT = "ux_strategies_author_name"
"""The unique ``(author_id, name)``: a name is taken only within one author."""


class SqlAlchemyStrategyRepository:
    """Implements ``StrategyRepositoryPort`` against the ``strategies`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, strategy: Strategy, webhook_secret_hash: str) -> None:
        self._session.add(
            StrategyRow(
                id=strategy.id,
                name=strategy.name,
                exchange=strategy.policy.exchange.value,
                venue=strategy.policy.venue.value,
                settlement_currency=strategy.policy.settlement_currency.value,
                author_id=strategy.author_id,
                enabled=strategy.enabled,
                visibility=strategy.visibility.value,
                fill_mode=strategy.policy.fill_mode.value,
                webhook_secret_hash=webhook_secret_hash,
                allowed_pairs=strategy.allowed_pairs.sorted(),
            )
        )
        await self._session.flush()

    async def replace_webhook_secret_hash(
        self, strategy_id: UUID, webhook_secret_hash: str
    ) -> None:
        row = await self._session.get(StrategyRow, strategy_id)
        if row is None:
            raise LookupError(f"no strategy row under id {strategy_id}")
        row.webhook_secret_hash = webhook_secret_hash
        row.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        row = await self._session.get(StrategyRow, strategy_id)
        return None if row is None else _to_domain(row)

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        """``SELECT ... FOR UPDATE`` -- see ``StrategyRepositoryPort``'s own
        docstring for why. Two concurrent transactions calling this for the
        SAME id serialize here: the second blocks until the first commits or
        rolls back, then re-reads whatever the first one left behind
        (tasks.md 2d.3; verified against real Postgres by
        ``tests/strategies/infrastructure/test_update_strategy_concurrency.py``).

        ``populate_existing`` makes the locked read return what the database holds
        NOW even when this session already loaded the row (``ReplaceAllowedPairs``
        reads it unlocked first, to decide whether a venue call is needed). Without
        it the ORM hands back the earlier, stale values and the re-check under the
        lock would be checking nothing."""
        row = (
            await self._session.execute(
                select(StrategyRow)
                .where(StrategyRow.id == strategy_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:
        """Ordered by name so the listing is stable between calls. Creation
        order would put a renamed strategy somewhere the reader does not
        expect, and there are tens of these, not thousands.

        Excludes archived strategies unless ``include_archived=True``
        (spec: strategy-lifecycle § "Strategy Listing Excludes Archived By
        Default").

        Unscoped: every author's strategies, for the callers that work on the
        system's strategies and not a user's (it takes no ``user_id``). The
        strategies router never reads through this: it uses
        ``AuthorStrategyRepository``, which lists one author's."""
        stmt = select(StrategyRow).order_by(StrategyRow.name)
        if not include_archived:
            stmt = stmt.where(StrategyRow.archived_at.is_(None))
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def update(self, strategy: Strategy) -> None:
        """Writes only the mutable fields.

        ``exchange``, ``venue`` and ``settlement_currency`` are deliberately absent: a
        strategy cannot be moved between capital pools (see
        ``UpdateStrategy``), and leaving them out of the statement means this
        adapter cannot do it even if a caller asks.
        """
        row = await self._session.get(StrategyRow, strategy.id)
        if row is None:
            raise LookupError(f"no strategy row under id {strategy.id}")

        row.name = strategy.name
        row.enabled = strategy.enabled
        row.visibility = strategy.visibility.value
        row.fill_mode = strategy.policy.fill_mode.value
        row.allowed_pairs = strategy.allowed_pairs.sorted()
        # Archive is terminal (design.md § 8): every OTHER caller of
        # ``update()`` (``UpdateStrategy``, ``ReplaceAllowedPairs``) reads
        # ``strategy`` from this same row first and only replaces unrelated
        # fields, so ``archived_at`` round-trips unchanged for them --
        # ``ArchiveStrategy`` is the only caller that ever sets it.
        row.archived_at = strategy.archived_at
        row.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def delete(self, strategy_id: UUID) -> None:
        """One ``DELETE`` statement, flushed and not committed.

        A foreign key that still points at the row refuses it in the database. That
        is recognised by the SQLSTATE (``23503``, ``foreign_key_violation``) and the
        violated constraint is reported by its NAME, never by the message text, which
        follows the server's locale. Any other integrity error propagates unchanged.
        The failed statement leaves the transaction aborted: the caller rolls back.
        """
        try:
            await self._session.execute(
                sa_delete(StrategyRow).where(StrategyRow.id == strategy_id)
            )
            await self._session.flush()
        except IntegrityError as error:
            cause = error.orig.__cause__  # type: ignore[union-attr]
            if getattr(cause, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
                raise StrategyStillReferenced(getattr(cause, "constraint_name", None)) from error
            raise


class AuthorStrategyRepository(SqlAlchemyStrategyRepository):
    """The strategies of ONE author (multi-user design AD8, tasks.md D.4).

    Every read answers only ``author_id``'s strategies, so another user's strategy
    is ``None`` here exactly as one that does not exist, and each use case that
    reads through this repository answers the same 404 for both. The locked read is
    the base class's ``SELECT ... FOR UPDATE`` with the same filter, so a write that
    takes it holds the row lock it always held: it only never locks a row that is
    not the caller's.

    The writes (``update``, ``delete``, ``replace_webhook_secret_hash``) are the base
    class's, by id: every use case reads the strategy through this class first and
    stops on ``None``, and an author never changes. ``insert`` stays the base's too.
    """

    def __init__(self, session: AsyncSession, author_id: UUID) -> None:
        super().__init__(session)
        self._author_id = author_id

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        row = (
            await self._session.execute(
                select(StrategyRow).where(
                    StrategyRow.id == strategy_id, StrategyRow.author_id == self._author_id
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        row = (
            await self._session.execute(
                select(StrategyRow)
                .where(StrategyRow.id == strategy_id, StrategyRow.author_id == self._author_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:
        """The author's own strategies, ordered by name. The name is unique only
        within one author, so no two rows here share one."""
        stmt = (
            select(StrategyRow)
            .where(StrategyRow.author_id == self._author_id)
            .order_by(StrategyRow.name)
        )
        if not include_archived:
            stmt = stmt.where(StrategyRow.archived_at.is_(None))
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]


def is_name_conflict(error: IntegrityError) -> bool:
    """Whether the database refused a write because the author already has a strategy
    of that name (``ux_strategies_author_name``, migration 0033). Read from the
    violated constraint's NAME, never from the message text, which follows the
    server's locale; any other integrity failure is not a name clash."""
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None) == AUTHOR_NAME_CONSTRAINT


def _to_domain(row: StrategyRow) -> Strategy:
    return Strategy(
        id=row.id,
        name=row.name,
        policy=AllocationPolicy(
            exchange=Exchange(row.exchange),
            venue=Venue(row.venue),
            settlement_currency=Currency(row.settlement_currency),
            fill_mode=FillMode(row.fill_mode),
        ),
        author_id=row.author_id,
        enabled=row.enabled,
        visibility=Visibility(row.visibility),
        allowed_pairs=AllowedPairs(frozenset(row.allowed_pairs)),
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
