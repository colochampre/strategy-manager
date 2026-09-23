"""Migration ``0023`` -- ``booking_proposals`` (design.md § 3
"``booking_proposals`` -- migration 0023"; spec: venue-close-booking
§ "Proposal Prepared From a Frozen Snapshot, At Most One Pending").

Follows the exact fixture pattern of
``tests/migrations/test_0022_execution_attempt_origin.py``: a dedicated
throwaway database, ``alembic upgrade head`` in a subprocess so alembic's own
``asyncio.run`` never collides with the test's already-running loop, dropped
at teardown.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings


def _constraint_name(error: IntegrityError) -> str | None:
    """The asyncpg driver wraps its own ``PostgresError`` (which carries
    ``constraint_name`` directly, not nested under a ``.diag``) as
    ``__cause__`` of SQLAlchemy's DBAPI wrapper exception -- see
    ``sqlalchemy.dialects.postgresql.asyncpg``'s ``raise translated_error
    from error``. Reading it here means every CHECK/unique/FK assertion in
    this file identifies the violated constraint BY NAME, never by message
    text (this change's binding testing rule, carried over from Unit 6a's
    own requirement on ``ApproveBooking``)."""
    cause = error.orig.__cause__
    return getattr(cause, "constraint_name", None)


pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_booking_proposals"

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}

_KIND_CONSTRAINT = "ck_booking_proposals_kind"
_SIDE_CONSTRAINT = "ck_booking_proposals_side"
_QUANTITY_CONSTRAINT = "ck_booking_proposals_quantity_positive"
_DECIDED_AT_CONSTRAINT = "ck_booking_proposals_decided_at"
_REJECTED_REASON_CONSTRAINT = "ck_booking_proposals_rejected_reason"
_EXECUTION_ATTEMPT_CONSTRAINT = "ck_booking_proposals_execution_attempt_only_approved"
_PENDING_UNIQUE_INDEX = "ux_booking_proposals_pending_per_discrepancy"
_DISCREPANCY_FK = "fk_booking_proposals_discrepancy"


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


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
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
    return result


def _run_alembic_ok(database_url: str, *args: str) -> None:
    result = _run_alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic_ok(url, "upgrade", "head")

    yield url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _seed_discrepancy(conn: AsyncConnection) -> tuple[UUID, UUID, UUID]:
    """Seeds a strategy + signal + reservation (the allocation) and a
    CONFIRMED reconciliation_discrepancies row, returning
    ``(discrepancy_id, strategy_id, allocation_id)``.

    Each call uses a freshly randomised symbol: ``ux_reconciliation_open_per_symbol``
    permits at most one OPEN discrepancy per pool+symbol, and this fixture is
    called once per test against the same module-scoped throwaway database,
    so a fixed symbol would collide with every prior call's still-OPEN row."""
    strategy_id, signal_id, allocation_id, discrepancy_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    scan_id = uuid4()
    symbol = f"STX{uuid4().hex[:10].upper()}USDT.P"
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, :exchange, :venue, :settlement_currency, true, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"strategy-{strategy_id}", **_POOL},
    )
    await conn.execute(
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
    await conn.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
            "amount, status, expires_at) "
            "VALUES (:id, :strategy_id, :signal_id, :exchange, :venue, "
            ":settlement_currency, 100, 'FILLED', now() + interval '1 hour')"
        ),
        {"id": allocation_id, "strategy_id": strategy_id, "signal_id": signal_id, **_POOL},
    )
    await conn.execute(
        text(
            "INSERT INTO reconciliation_discrepancies "
            "(id, exchange, venue, settlement_currency, symbol, kind, "
            "venue_net_base, ledger_net_base, status, confirmed_at, "
            "first_scan_id, last_scan_id) "
            "VALUES (:id, :exchange, :venue, :settlement_currency, :symbol, "
            "'ATTRIBUTABLE_FULL_CLOSE', 0, 0.5, 'CONFIRMED', now(), "
            ":scan_id, :scan_id)"
        ),
        {"id": discrepancy_id, "scan_id": scan_id, "symbol": symbol, **_POOL},
    )
    return discrepancy_id, strategy_id, allocation_id


def _fills_snapshot() -> list[dict[str, str | None]]:
    return [
        {
            "exchange_fill_id": "1001",
            "exchange_order_id": "5001",
            "side": "SELL",
            "quantity": "0.5",
            "price": "142.37",
            "fee": "0.03913",
            "fee_currency": "USDT",
            "filled_at": "2026-09-23T01:02:03.456000+00:00",
        }
    ]


def _pending_proposal_params(
    *, discrepancy_id: UUID, strategy_id: UUID, allocation_id: UUID, job_id: UUID
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "discrepancy_id": discrepancy_id,
        "symbol": "STXUSDT.P",
        "kind": "ATTRIBUTABLE_FULL_CLOSE",
        "allocation_id": allocation_id,
        "strategy_id": strategy_id,
        "side": "SELL",
        "quantity": "0.5",
        "observed_venue_net_base": "0",
        "observed_ledger_net_base": "0.5",
        "observed_allocation_ids": [allocation_id],
        "fills": json.dumps(_fills_snapshot()),
        "client_order_id": f"vnu:bybit:5001-{uuid4()}",
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
        "prepared_by_job_id": job_id,
        **_POOL,
    }


_INSERT_PENDING = text(
    "INSERT INTO booking_proposals "
    "(id, discrepancy_id, exchange, venue, settlement_currency, symbol, kind, "
    "allocation_id, strategy_id, side, quantity, observed_venue_net_base, "
    "observed_ledger_net_base, observed_allocation_ids, fills, client_order_id, "
    "expires_at, prepared_by_job_id) "
    "VALUES (:id, :discrepancy_id, :exchange, :venue, :settlement_currency, :symbol, "
    ":kind, :allocation_id, :strategy_id, :side, :quantity, :observed_venue_net_base, "
    ":observed_ledger_net_base, :observed_allocation_ids, :fills, :client_order_id, "
    ":expires_at, :prepared_by_job_id)"
)


async def test_columns_round_trip_a_valid_pending_proposal(conn: AsyncConnection) -> None:
    """Smoke test for every column's shape: a fully-populated PENDING row,
    inserted and read back byte-identical on every frozen field, including
    the JSONB ``fills`` snapshot and the ``uuid[]`` observed allocations."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    job_id = uuid4()
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=job_id,
    )
    await conn.execute(_INSERT_PENDING, params)
    await conn.commit()

    row = (
        await conn.execute(
            text("SELECT * FROM booking_proposals WHERE id = :id"),
            {"id": params["id"]},
        )
    ).mappings().one()

    assert row["discrepancy_id"] == discrepancy_id
    assert row["kind"] == "ATTRIBUTABLE_FULL_CLOSE"
    assert row["side"] == "SELL"
    assert row["quantity"] == pytest.approx(0.5)
    assert row["observed_allocation_ids"] == [allocation_id]
    assert row["fills"] == _fills_snapshot()
    assert row["state"] == "PENDING"
    assert row["decided_at"] is None
    assert row["execution_attempt_id"] is None
    assert row["prepared_by_job_id"] == job_id


async def test_kind_check_refuses_ambiguous_partial_reduce(conn: AsyncConnection) -> None:
    """``AMBIGUOUS_PARTIAL_REDUCE`` is unbookable (design.md § 5): the table
    itself must refuse it, identified by CONSTRAINT NAME."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["kind"] = "AMBIGUOUS_PARTIAL_REDUCE"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == _KIND_CONSTRAINT
    await conn.rollback()


async def test_kind_check_refuses_no_matching_allocation(conn: AsyncConnection) -> None:
    """The second unbookable verdict, same CHECK."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["kind"] = "NO_MATCHING_ALLOCATION"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == _KIND_CONSTRAINT
    await conn.rollback()


async def test_kind_check_accepts_attributable_single_allocation(
    conn: AsyncConnection,
) -> None:
    """The other bookable kind is accepted -- proves the CHECK restricts to
    exactly two values, not zero."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["kind"] = "ATTRIBUTABLE_SINGLE_ALLOCATION"

    await conn.execute(_INSERT_PENDING, params)
    await conn.commit()


async def test_side_check_refuses_unknown_side(conn: AsyncConnection) -> None:
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["side"] = "HOLD"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == _SIDE_CONSTRAINT
    await conn.rollback()


async def test_quantity_check_refuses_zero(conn: AsyncConnection) -> None:
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["quantity"] = "0"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == _QUANTITY_CONSTRAINT
    await conn.rollback()


async def test_quantity_check_refuses_negative(conn: AsyncConnection) -> None:
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    params["quantity"] = "-0.5"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == _QUANTITY_CONSTRAINT
    await conn.rollback()


async def test_decided_at_check_refuses_approved_without_timestamp(
    conn: AsyncConnection,
) -> None:
    """State CHECK 1: a non-PENDING row always carries ``decided_at``."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, params)

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text(
                "UPDATE booking_proposals SET state = 'REJECTED', "
                "decision_reason = 'stale' WHERE id = :id"
            ),
            {"id": params["id"]},
        )
    assert _constraint_name(excinfo.value) == _DECIDED_AT_CONSTRAINT
    await conn.rollback()


async def test_rejected_reason_check_refuses_blank_reason(conn: AsyncConnection) -> None:
    """State CHECK 2: REJECTED always carries a non-blank reason --
    ``btrim(coalesce(...))`` catches whitespace-only too, not only NULL."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, params)

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text(
                "UPDATE booking_proposals SET state = 'REJECTED', decided_at = now(), "
                "decision_reason = '   ' WHERE id = :id"
            ),
            {"id": params["id"]},
        )
    assert _constraint_name(excinfo.value) == _REJECTED_REASON_CONSTRAINT
    await conn.rollback()


async def test_rejected_reason_check_accepts_non_blank_reason(conn: AsyncConnection) -> None:
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, params)

    await conn.execute(
        text(
            "UPDATE booking_proposals SET state = 'REJECTED', decided_at = now(), "
            "decision_reason = 'attribution wrong' WHERE id = :id"
        ),
        {"id": params["id"]},
    )
    await conn.commit()


async def test_execution_attempt_check_refuses_when_not_approved(
    conn: AsyncConnection,
) -> None:
    """State CHECK 3: ``execution_attempt_id`` is set if and only if
    APPROVED. Isolated from CHECKs 1/2 by using REJECTED with a valid
    ``decided_at``/``decision_reason`` and only violating this one."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, params)

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text(
                "UPDATE booking_proposals SET state = 'REJECTED', decided_at = now(), "
                "decision_reason = 'attribution wrong', execution_attempt_id = :xid "
                "WHERE id = :id"
            ),
            {"id": params["id"], "xid": uuid4()},
        )
    assert _constraint_name(excinfo.value) == _EXECUTION_ATTEMPT_CONSTRAINT
    await conn.rollback()


async def test_pending_unique_index_refuses_second_pending_per_discrepancy(
    conn: AsyncConnection,
) -> None:
    """This partial unique index IS prepare's idempotency (design.md § 3)."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    first = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, first)
    await conn.commit()

    second = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, second)
    assert _constraint_name(excinfo.value) == _PENDING_UNIQUE_INDEX
    await conn.rollback()


async def test_pending_unique_index_allows_new_pending_after_prior_decided(
    conn: AsyncConnection,
) -> None:
    """The partial index restricts PENDING only: once the first proposal is
    decided, a fresh PENDING proposal for the same discrepancy is allowed."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    first = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, first)
    await conn.execute(
        text(
            "UPDATE booking_proposals SET state = 'REJECTED', decided_at = now(), "
            "decision_reason = 'stale' WHERE id = :id"
        ),
        {"id": first["id"]},
    )
    await conn.commit()

    second = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, second)
    await conn.commit()


async def test_discrepancy_fk_refuses_delete_while_proposal_exists(
    conn: AsyncConnection,
) -> None:
    """No ``ON DELETE CASCADE`` (module docstring): deleting the discrepancy
    a proposal was prepared from must fail, not silently take the proposal
    with it."""
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    params = _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )
    await conn.execute(_INSERT_PENDING, params)
    await conn.commit()

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text("DELETE FROM reconciliation_discrepancies WHERE id = :id"),
            {"id": discrepancy_id},
        )
    assert _constraint_name(excinfo.value) == _DISCREPANCY_FK
    await conn.rollback()


async def test_pending_and_discrepancy_indexes_exist(conn: AsyncConnection) -> None:
    """``ix_booking_proposals_pending`` and ``ix_booking_proposals_discrepancy``
    both exist -- the list endpoint / expiry sweep and the REJECTED-suppression
    lookup respectively (design.md § 3)."""
    rows = (
        await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'booking_proposals'"
            )
        )
    ).scalars().all()
    assert "ix_booking_proposals_pending" in rows
    assert "ix_booking_proposals_discrepancy" in rows
    assert _PENDING_UNIQUE_INDEX in rows


def test_downgrade_drops_unconditionally_even_with_rows(database_url: str) -> None:
    """Unlike 0022's guarded downgrade, 0023 DROPs the table unconditionally
    -- no refusal clause, regardless of how many rows exist (module
    docstring: a proposal is not money)."""

    async def _insert_a_row_and_count() -> int:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(
                    connection
                )
                params = _pending_proposal_params(
                    discrepancy_id=discrepancy_id,
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    job_id=uuid4(),
                )
                await connection.execute(_INSERT_PENDING, params)
                await connection.commit()
                count = (
                    await connection.execute(text("SELECT COUNT(*) FROM booking_proposals"))
                ).scalar_one()
                return int(count)
        finally:
            await engine.dispose()

    async def _table_exists() -> bool:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return bool(
                    (
                        await connection.execute(
                            text(
                                "SELECT 1 FROM information_schema.tables WHERE "
                                "table_name = 'booking_proposals'"
                            )
                        )
                    ).scalar_one_or_none()
                )
        finally:
            await engine.dispose()

    # >= 1, not == 1: this test runs against the same module-scoped throwaway
    # database as every other test in this file, several of which commit
    # their own booking_proposals rows -- the point here is only that rows
    # exist at all when the unconditional downgrade runs.
    row_count = asyncio.run(_insert_a_row_and_count())
    assert row_count >= 1

    _run_alembic_ok(database_url, "downgrade", "0022")
    assert asyncio.run(_table_exists()) is False

    # Rehearse the round trip back to head so the module-scoped fixture's
    # later tests (in file-declaration order, pytest runs this file's other
    # tests before this one due to module-scoped `database_url`) are
    # unaffected -- this test intentionally runs last (name sorts after
    # every other `test_*` in this file alphabetically is NOT guaranteed by
    # pytest, so re-upgrading here is required, not cosmetic).
    _run_alembic_ok(database_url, "upgrade", "head")
    assert asyncio.run(_table_exists()) is True


# --- Guards added in review: each closes a way to fail without a log line ------


async def _proposal_params(conn: AsyncConnection) -> dict[str, object]:
    discrepancy_id, strategy_id, allocation_id = await _seed_discrepancy(conn)
    return _pending_proposal_params(
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        job_id=uuid4(),
    )


async def test_state_check_refuses_a_state_outside_the_five(conn: AsyncConnection) -> None:
    """A misspelt state satisfies all three state-machine CHECKs vacuously and
    drops out of both partial indexes: the proposal would stop being listed
    and stop blocking a second one, with no error anywhere."""
    params = await _proposal_params(conn)
    await conn.execute(_INSERT_PENDING, params)

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text(
                "UPDATE booking_proposals SET state = 'DECLINED', decided_at = now() "
                "WHERE id = :id"
            ),
            {"id": params["id"]},
        )
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_state"
    await conn.rollback()


async def test_fills_check_refuses_an_empty_array(conn: AsyncConnection) -> None:
    """match_fills refuses zero unrecorded fills, so a proposal with none can
    only come from a bug -- and approving it would write an attempt with no
    ledger rows behind it."""
    params = await _proposal_params(conn)
    params["fills"] = "[]"

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_fills_nonempty_array"
    await conn.rollback()


async def test_fills_check_refuses_a_non_array(conn: AsyncConnection) -> None:
    params = await _proposal_params(conn)
    params["fills"] = '{"exchange_fill_id": "1"}'

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_fills_nonempty_array"
    await conn.rollback()


async def test_observed_allocation_ids_check_refuses_an_empty_array(
    conn: AsyncConnection,
) -> None:
    """Both bookable verdicts have at least one open allocation; an empty
    frozen set would make the freshness re-check compare against nothing."""
    params = await _proposal_params(conn)
    params["observed_allocation_ids"] = []

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_single_allocation"
    await conn.rollback()


async def test_single_allocation_check_refuses_several_observed_allocations(
    conn: AsyncConnection,
) -> None:
    """A full close over several allocations cannot be attributed to one
    without an invented split; the table refuses to hold such a proposal."""
    params = await _proposal_params(conn)
    params["observed_allocation_ids"] = [params["allocation_id"], uuid4()]

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_single_allocation"
    await conn.rollback()


async def test_single_allocation_check_refuses_an_allocation_that_was_not_observed(
    conn: AsyncConnection,
) -> None:
    params = await _proposal_params(conn)
    params["observed_allocation_ids"] = [uuid4()]

    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(_INSERT_PENDING, params)
    assert _constraint_name(excinfo.value) == "ck_booking_proposals_single_allocation"
    await conn.rollback()
