"""Tier B: ``SqlAlchemyBookingProposalRepository`` against a real ``alembic
upgrade head`` database (design.md § 3 "``booking_proposals`` -- migration
0023"; § 11 "Rejection semantics and suppression"; spec:
venue-close-booking).

Follows ``test_discrepancy_repository_integration.py``'s own pattern: a
dedicated throwaway database, migrated to head, dropped at teardown. That
file already proves the raw SQL shape of ``booking_proposals``' own
constraints (``test_0023_booking_proposals.py``); this one proves the
REPOSITORY drives them correctly -- the CAS update under real concurrency,
the partial unique index surfacing as a distinguishable outcome rather than
a bare exception, the Decimal<->JSON-string discipline the schema itself
cannot enforce, and the REJECTED-suppression lookup's scale-independent
equality. No fake can prove any of this: a fake
``BookingProposalRepositoryPort`` would only ever prove this file's own
assumptions about Postgres are self-consistent.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.reconciliation.application.ports import (
    BookingProposalRecord,
    NewBookingProposal,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind, Observation
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_DB_NAME = "strategy_manager_test_booking_proposal_repo"

_POOL = ("pionex", "spot", "USDT")
NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _drop_database_if_exists(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _run_alembic(database_url: str, *args: str) -> None:
    """Runs an alembic subcommand in a subprocess so alembic's own
    ``asyncio.run`` never collides with the test's already-running loop."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic(url, "upgrade", "head")

    yield url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _clean_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        # ONLY booking_proposals: nothing FKs into it, so no CASCADE is
        # needed. ``reconciliation_discrepancies``/``reservations``/
        # ``signals``/``strategies`` are deliberately left alone -- every
        # ``_seed_discrepancy`` call uses a fresh random id and a
        # randomised symbol, so they never collide across tests, and a
        # CASCADE-ing TRUNCATE of ``reservations`` reaches the
        # append-only ``ledger_entries`` table (CLAUDE.md rule 6) and is
        # refused by its own trigger. ``list_pending``/``has_matching_rejection``
        # read across the whole table unscoped, so booking_proposals is
        # the one table that DOES need clearing between tests.
        await conn.execute(text("TRUNCATE booking_proposals"))


async def _seed_discrepancy(
    session: AsyncSession,
) -> tuple[UUID, UUID, UUID]:
    """Seeds a strategy + signal + reservation (the allocation) and a
    CONFIRMED ``reconciliation_discrepancies`` row, returning
    ``(discrepancy_id, strategy_id, allocation_id)``. Mirrors
    ``test_0023_booking_proposals.py``'s own ``_seed_discrepancy`` --
    proven fixture shape, adapted to an ``AsyncSession`` rather than a bare
    ``AsyncConnection``.

    Each call uses a freshly randomised symbol: ``ux_reconciliation_open_per_symbol``
    permits at most one OPEN discrepancy per pool+symbol, and several tests
    in this module share one throwaway database."""

    strategy_id, signal_id, allocation_id, discrepancy_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    scan_id = uuid4()
    symbol = f"STX{uuid4().hex[:10].upper()}USDT.P"
    await session.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, :exchange, :venue, :settlement_currency, true, 'PARTIAL')"
        ),
        {
            "id": strategy_id,
            "name": f"strategy-{strategy_id}",
            "exchange": _POOL[0],
            "venue": _POOL[1],
            "settlement_currency": _POOL[2],
        },
    )
    await session.execute(
        text(
            "INSERT INTO signals "
            "(id, strategy_id, idempotency_key, raw_payload, action, contracts, "
            "position_size, price, symbol, signal_type) "
            "VALUES (:id, :strategy_id, :idempotency_key, '{}', 'sell', 1, 1, 1, "
            ":symbol, :signal_type)"
        ),
        {
            "id": signal_id,
            "strategy_id": strategy_id,
            "idempotency_key": f"k-{signal_id}",
            "signal_type": str(strategy_id),
            "symbol": symbol,
        },
    )
    await session.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
            "amount, status, expires_at) "
            "VALUES (:id, :strategy_id, :signal_id, :exchange, :venue, "
            ":settlement_currency, 100, 'FILLED', now() + interval '1 hour')"
        ),
        {
            "id": allocation_id,
            "strategy_id": strategy_id,
            "signal_id": signal_id,
            "exchange": _POOL[0],
            "venue": _POOL[1],
            "settlement_currency": _POOL[2],
        },
    )
    await session.execute(
        text(
            "INSERT INTO reconciliation_discrepancies "
            "(id, exchange, venue, settlement_currency, symbol, kind, "
            "venue_net_base, ledger_net_base, status, confirmed_at, "
            "first_scan_id, last_scan_id) "
            "VALUES (:id, :exchange, :venue, :settlement_currency, :symbol, "
            "'ATTRIBUTABLE_FULL_CLOSE', 0, 0.5, 'CONFIRMED', now(), "
            ":scan_id, :scan_id)"
        ),
        {
            "id": discrepancy_id,
            "scan_id": scan_id,
            "symbol": symbol,
            "exchange": _POOL[0],
            "venue": _POOL[1],
            "settlement_currency": _POOL[2],
        },
    )
    await session.commit()
    return discrepancy_id, strategy_id, allocation_id


def _fill(**overrides: object) -> ProposedFillSnapshot:
    defaults: dict[str, object] = {
        "exchange_fill_id": "1001",
        "exchange_order_id": "5001",
        "side": "SELL",
        "quantity": Decimal("0.5"),
        "price": Decimal("142.37"),
        "fee": Decimal("0.03913"),
        "fee_currency": "USDT",
        "filled_at": NOW,
    }
    defaults.update(overrides)
    return ProposedFillSnapshot(**defaults)  # type: ignore[arg-type]


def _proposal(
    *,
    discrepancy_id: UUID,
    strategy_id: UUID,
    allocation_id: UUID,
    job_id: UUID | None = None,
    **overrides: object,
) -> NewBookingProposal:
    defaults: dict[str, object] = {
        "discrepancy_id": discrepancy_id,
        "exchange": _POOL[0],
        "venue": _POOL[1],
        "settlement_currency": _POOL[2],
        # The MARKET KEY (design.md § 13), never a venue spelling -- this
        # repository does no symbol normalisation of its own, so there is
        # no boundary here to cross-spell.
        "symbol": "STXUSDT.P",
        "kind": DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        "allocation_id": allocation_id,
        "strategy_id": strategy_id,
        "side": "SELL",
        "quantity": Decimal("0.5"),
        "observed_venue_net_base": Decimal("0"),
        "observed_ledger_net_base": Decimal("0.5"),
        "observed_allocation_ids": [allocation_id],
        "fills": [_fill()],
        "client_order_id": f"vnu:pionex:{uuid4()}",
        "expires_at": NOW + timedelta(hours=24),
        "prepared_by_job_id": job_id if job_id is not None else uuid4(),
    }
    defaults.update(overrides)
    return NewBookingProposal(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# insert -- the frozen-column write, and its one distinguishable outcome
# --------------------------------------------------------------------------


async def test_insert_writes_every_frozen_column_byte_identical(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        proposal = _proposal(
            discrepancy_id=discrepancy_id, strategy_id=strategy_id, allocation_id=allocation_id
        )
        record = await repo.insert(proposal)
        await session.commit()

    assert record is not None
    assert isinstance(record, BookingProposalRecord)
    assert record.discrepancy_id == discrepancy_id
    assert record.kind is DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE
    assert record.side == "SELL"
    assert record.quantity == Decimal("0.5")
    assert record.observed_allocation_ids == (allocation_id,)
    assert record.client_order_id == proposal.client_order_id
    assert record.state == "PENDING"
    assert record.decided_at is None
    assert record.execution_attempt_id is None
    assert len(record.fills) == 1
    fill = record.fills[0]
    assert fill.exchange_fill_id == "1001"
    assert fill.exchange_order_id == "5001"
    assert fill.side == "SELL"
    assert fill.quantity == Decimal("0.5")
    assert fill.price == Decimal("142.37")
    assert fill.fee == Decimal("0.03913")
    assert fill.fee_currency == "USDT"
    assert fill.filled_at == NOW


async def test_insert_second_pending_proposal_for_same_discrepancy_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The partial unique index ``ux_booking_proposals_pending_per_discrepancy``,
    driven by the repository: a second PENDING proposal for the same
    discrepancy writes nothing and surfaces as ``None``, never an
    unhandled ``IntegrityError`` -- distinguished by CONSTRAINT NAME."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        first = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert first is not None

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        second = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        # Nothing raised: the collision is a returned outcome. The session
        # must still be usable afterwards -- proving the SAVEPOINT, not the
        # whole transaction, absorbed the aborted INSERT.
        pending = await repo.list_pending(limit=10)
        await session.commit()

    assert second is None
    assert [record.id for record in pending] == [first.id]


async def test_insert_of_an_unrelated_integrity_violation_propagates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Only the ONE named collision is swallowed. A CHECK violation (here:
    ``ck_booking_proposals_quantity_positive``) is a bug and must still
    raise, never be silently folded into "already pending"."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        with pytest.raises(IntegrityError):
            await repo.insert(
                _proposal(
                    discrepancy_id=discrepancy_id,
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    quantity=Decimal("0"),
                )
            )


# --------------------------------------------------------------------------
# fills JSONB -- Decimal precision as a JSON STRING, never a JSON number
# --------------------------------------------------------------------------


async def test_fills_precision_survives_as_json_strings_not_numbers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A value a float would silently corrupt, round-tripped exactly --
    and, directly against Postgres, proven to be stored as a JSON STRING
    (``jsonb_typeof(... ) = 'string'``), which is the only thing the
    schema itself cannot enforce (migration 0023's own self-audit)."""

    precise = Decimal("0.100000000000000001")
    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        record = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                fills=[_fill(quantity=precise, price=precise, fee=precise)],
            )
        )
        await session.commit()
        assert record is not None

        row = (
            await session.execute(
                text(
                    "SELECT jsonb_typeof(fills->0->'quantity') AS q_type, "
                    "jsonb_typeof(fills->0->'price') AS p_type, "
                    "jsonb_typeof(fills->0->'fee') AS f_type "
                    "FROM booking_proposals WHERE id = :id"
                ),
                {"id": record.id},
            )
        ).mappings().one()

    assert row["q_type"] == "string"
    assert row["p_type"] == "string"
    assert row["f_type"] == "string"
    fill = record.fills[0]
    assert fill.quantity == precise
    assert fill.price == precise
    assert fill.fee == precise


# --------------------------------------------------------------------------
# get_for_update
# --------------------------------------------------------------------------


async def test_get_for_update_returns_the_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert inserted is not None

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        locked = await repo.get_for_update(inserted.id)
        await session.commit()

    assert locked.id == inserted.id
    assert locked.state == "PENDING"


async def test_get_for_update_of_an_unknown_id_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        with pytest.raises(NoResultFound):
            await repo.get_for_update(uuid4())


# --------------------------------------------------------------------------
# mark_state -- the repository's ONLY update, and its CAS return value
# --------------------------------------------------------------------------


async def test_mark_state_transitions_pending_to_rejected_and_returns_true(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert inserted is not None

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        changed = await repo.mark_state(
            inserted.id,
            "REJECTED",
            NOW,
            decided_by="owner",
            decision_reason="not real, ignore",
        )
        await session.commit()

    assert changed is True

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        record = await repo.get_for_update(inserted.id)
        await session.commit()

    assert record.state == "REJECTED"
    assert record.decided_at == NOW
    assert record.decided_by == "owner"
    assert record.decision_reason == "not real, ignore"


async def test_mark_state_a_second_time_returns_false_and_does_not_overwrite(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The CAS, proven sequentially (the concurrency test below proves it
    under a real race): once a proposal is no longer PENDING, a second
    ``mark_state`` call changes zero rows and must say so."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert inserted is not None

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        first = await repo.mark_state(
            inserted.id, "REJECTED", NOW, decided_by="owner", decision_reason="first"
        )
        await session.commit()
    assert first is True

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        second = await repo.mark_state(
            inserted.id,
            "REJECTED",
            NOW + timedelta(minutes=1),
            decided_by="someone-else",
            decision_reason="second, must not apply",
        )
        await session.commit()
    assert second is False

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        record = await repo.get_for_update(inserted.id)
        await session.commit()

    assert record.decision_reason == "first"
    assert record.decided_by == "owner"
    assert record.decided_at == NOW


async def test_mark_state_to_approved_with_no_execution_attempt_is_permitted_by_the_check(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ck_booking_proposals_execution_attempt_only_approved`` is a
    one-way implication (``state = 'APPROVED' OR execution_attempt_id IS
    NULL``): APPROVED with a still-NULL id is schema-legal. This exercises
    the repository's own APPROVED write path without needing a real
    ``execution_attempts`` row, which Unit 6a's ``ApproveBooking`` owns."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert inserted is not None

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        changed = await repo.mark_state(inserted.id, "APPROVED", NOW)
        await session.commit()

    assert changed is True


# --------------------------------------------------------------------------
# The FOR UPDATE CAS under a real race -- the load-bearing test
# --------------------------------------------------------------------------


async def test_concurrent_decisions_the_second_transaction_sees_non_pending_and_writes_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two genuinely separate sessions race to decide the SAME proposal.
    Without ``SELECT ... FOR UPDATE`` preceding the CAS, both could read
    PENDING before either commits and both would report ``True`` --
    exactly the bug this repository exists to make impossible."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
            )
        )
        await session.commit()
    assert inserted is not None
    proposal_id = inserted.id

    barrier = asyncio.Event()

    async def decide(reason: str) -> bool:
        async with session_factory() as session:
            repo = SqlAlchemyBookingProposalRepository(session)
            await barrier.wait()
            await repo.get_for_update(proposal_id)
            changed = await repo.mark_state(
                proposal_id, "REJECTED", NOW, decided_by="race", decision_reason=reason
            )
            await session.commit()
            return changed

    tasks = [asyncio.create_task(decide(f"racer-{i}")) for i in range(2)]
    await asyncio.sleep(0)  # let both tasks reach the barrier before releasing it
    barrier.set()
    results = await asyncio.gather(*tasks)

    assert sorted(results) == [False, True]

    async with session_factory() as session:
        repo = SqlAlchemyBookingProposalRepository(session)
        record = await repo.get_for_update(proposal_id)
        await session.commit()
    assert record.state == "REJECTED"
    # Exactly one racer's reason won -- the loser's write never happened.
    assert record.decision_reason in {"racer-0", "racer-1"}


# --------------------------------------------------------------------------
# list_pending
# --------------------------------------------------------------------------


async def test_list_pending_excludes_decided_rows_and_orders_by_expiry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        d1, s1, a1 = await _seed_discrepancy(session)
        d2, s2, a2 = await _seed_discrepancy(session)
        d3, s3, a3 = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)

        soon = await repo.insert(
            _proposal(
                discrepancy_id=d1,
                strategy_id=s1,
                allocation_id=a1,
                expires_at=NOW + timedelta(hours=1),
            )
        )
        later = await repo.insert(
            _proposal(
                discrepancy_id=d2,
                strategy_id=s2,
                allocation_id=a2,
                expires_at=NOW + timedelta(hours=5),
            )
        )
        decided = await repo.insert(
            _proposal(
                discrepancy_id=d3,
                strategy_id=s3,
                allocation_id=a3,
                expires_at=NOW + timedelta(hours=2),
            )
        )
        await session.commit()
        assert soon is not None
        assert later is not None
        assert decided is not None

        await repo.mark_state(decided.id, "REJECTED", NOW, decision_reason="not real")
        await session.commit()

        pending = await repo.list_pending(limit=10)

    assert [record.id for record in pending] == [soon.id, later.id]


# --------------------------------------------------------------------------
# has_matching_rejection -- design.md § 11's suppression lookup
# --------------------------------------------------------------------------


async def test_has_matching_rejection_true_for_the_identical_observation_triple(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                observed_venue_net_base=Decimal("2.5"),
                observed_ledger_net_base=Decimal("0"),
            )
        )
        await session.commit()
        assert inserted is not None
        await repo.mark_state(inserted.id, "REJECTED", NOW, decision_reason="not real")
        await session.commit()

        # Scale-independent Decimal VALUE equality, proven against real
        # Postgres: the column is Numeric(38,18), so the stored value is
        # padded to 18 decimal places, yet an unpadded Decimal("2.5") still
        # matches it -- true numeric equality, never string equality.
        suppressed = await repo.has_matching_rejection(
            discrepancy_id,
            Observation(
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                venue_net_base=Decimal("2.5"),
                ledger_net_base=Decimal("0"),
            ),
        )

    assert suppressed is True


async def test_has_matching_rejection_false_when_the_observation_moved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """design.md § 11: if the disagreement moves, the triple differs and a
    fresh proposal must be allowed -- suppression must not over-match."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                observed_venue_net_base=Decimal("2.5"),
                observed_ledger_net_base=Decimal("0"),
            )
        )
        await session.commit()
        assert inserted is not None
        await repo.mark_state(inserted.id, "REJECTED", NOW, decision_reason="not real")
        await session.commit()

        suppressed = await repo.has_matching_rejection(
            discrepancy_id,
            Observation(
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                venue_net_base=Decimal("3.1"),
                ledger_net_base=Decimal("0"),
            ),
        )

    assert suppressed is False


async def test_has_matching_rejection_false_when_the_proposal_is_still_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The suppression lookup reads REJECTED specifically -- a still-PENDING
    proposal (already blocking a fresh one via the partial unique index)
    must not also match here."""

    async with session_factory() as session:
        discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)
        inserted = await repo.insert(
            _proposal(
                discrepancy_id=discrepancy_id,
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                observed_venue_net_base=Decimal("2.5"),
                observed_ledger_net_base=Decimal("0"),
            )
        )
        await session.commit()
        assert inserted is not None

        suppressed = await repo.has_matching_rejection(
            discrepancy_id,
            Observation(
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                venue_net_base=Decimal("2.5"),
                ledger_net_base=Decimal("0"),
            ),
        )

    assert suppressed is False


# --------------------------------------------------------------------------
# expire_pending
# --------------------------------------------------------------------------


async def test_expire_pending_marks_only_overdue_pending_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        d1, s1, a1 = await _seed_discrepancy(session)
        d2, s2, a2 = await _seed_discrepancy(session)
        d3, s3, a3 = await _seed_discrepancy(session)
        repo = SqlAlchemyBookingProposalRepository(session)

        overdue = await repo.insert(
            _proposal(
                discrepancy_id=d1,
                strategy_id=s1,
                allocation_id=a1,
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        not_yet = await repo.insert(
            _proposal(
                discrepancy_id=d2,
                strategy_id=s2,
                allocation_id=a2,
                expires_at=NOW + timedelta(hours=1),
            )
        )
        already_rejected = await repo.insert(
            _proposal(
                discrepancy_id=d3,
                strategy_id=s3,
                allocation_id=a3,
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        await session.commit()
        assert overdue is not None
        assert not_yet is not None
        assert already_rejected is not None

        await repo.mark_state(already_rejected.id, "REJECTED", NOW, decision_reason="not real")
        await session.commit()

        expired_count = await repo.expire_pending(NOW)
        await session.commit()

        overdue_record = await repo.get_for_update(overdue.id)
        not_yet_record = await repo.get_for_update(not_yet.id)
        rejected_record = await repo.get_for_update(already_rejected.id)
        await session.commit()

    assert expired_count == 1
    assert overdue_record.state == "EXPIRED"
    assert overdue_record.decided_at == NOW
    assert not_yet_record.state == "PENDING"
    # Already-decided rows are untouched even though they are also overdue.
    assert rejected_record.state == "REJECTED"


# --- Naive datetimes are refused, never coerced --------------------------------
#
# A timezone-naive datetime reaching a TIMESTAMPTZ column is silently read in
# the session's timezone: a wrong but plausible decided_at or expires_at, with
# no error anywhere. Every clock in this system is timezone-aware, so a naive
# value can only be a bug, and the repository refuses it before any write.

_NAIVE = datetime(2026, 9, 23, 12, 0, 0)


async def test_insert_refuses_a_naive_expires_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        proposal = _proposal(
            discrepancy_id=uuid4(), strategy_id=uuid4(), allocation_id=uuid4(),
            expires_at=_NAIVE,
        )
        with pytest.raises(ValueError, match="expires_at"):
            await SqlAlchemyBookingProposalRepository(session).insert(proposal)


async def test_insert_refuses_a_naive_fill_timestamp(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        proposal = _proposal(
            discrepancy_id=uuid4(), strategy_id=uuid4(), allocation_id=uuid4(),
            fills=[_fill(filled_at=_NAIVE)],
        )
        with pytest.raises(ValueError, match="filled_at"):
            await SqlAlchemyBookingProposalRepository(session).insert(proposal)


async def test_mark_state_refuses_a_naive_decision_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="decided_at"):
            await SqlAlchemyBookingProposalRepository(session).mark_state(
                uuid4(), "REJECTED", _NAIVE, decision_reason="not mine"
            )


async def test_expire_pending_refuses_a_naive_now(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="now"):
            await SqlAlchemyBookingProposalRepository(session).expire_pending(_NAIVE)
