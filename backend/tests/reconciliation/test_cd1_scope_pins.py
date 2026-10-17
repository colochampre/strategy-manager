"""Scenarios of the PR 15 specs that design § L does not name as a test, each
its own pin (cd.1.34, as op.1.28 did for PR 14): the confirmed-discrepancies
backend takes no pool advisory lock in its new code and needs no credential in
its new tests.

They pass at once; each is proven by a mutation named in its docstring.

The unit's diff-scope scenarios (no migration, nothing outside
``reconciliation``, ``main.py`` and the config, no guard file, ``main.py``
removes no line) are checked once against the PR's base and recorded in
cd.1.34 of ``tasks.md``, not pinned here: a pin that diffs against ``main``
goes red on every later branch that legitimately touches another module.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND / "src" / "strategy_manager"

#: The new application and infrastructure files of the unit.
_NEW_SOURCE_FILES = (
    "reconciliation/domain/attention.py",
    "reconciliation/application/auto_book_pending.py",
    "reconciliation/application/announce_needs_owner.py",
    "reconciliation/application/read_confirmed.py",
    "reconciliation/application/confirmed_row.py",
    "reconciliation/infrastructure/system_order_ids_adapter.py",
    "reconciliation/infrastructure/strategy_name_adapter.py",
)

#: The unit's new test files.
_NEW_TEST_FILES = (
    "tests/reconciliation/domain/test_attention.py",
    "tests/reconciliation/application/test_auto_book_pending.py",
    "tests/reconciliation/application/test_announce_needs_owner.py",
    "tests/reconciliation/application/test_read_confirmed.py",
    "tests/reconciliation/application/auto_booking_support.py",
    "tests/reconciliation/application/test_auto_booking_integration.py",
    "tests/reconciliation/application/test_auto_booking_concurrency.py",
    "tests/reconciliation/application/test_auto_booking_deploy_integration.py",
    "tests/reconciliation/infrastructure/test_confirmed_router.py",
    "tests/reconciliation/infrastructure/test_confirmed_read_integration.py",
    "tests/reconciliation/infrastructure/test_system_order_ids_adapter_integration.py",
)


_ADVISORY = re.compile(r"pg_advisory|advisory_lock|AdvisoryLock|pool_lock", re.IGNORECASE)


@pytest.mark.parametrize("relative", _NEW_SOURCE_FILES)
def test_no_new_source_file_takes_or_imports_a_pool_advisory_lock(relative: str) -> None:
    """Design C3: the automatic step takes a row lock only. Mutation: import
    ``pg_advisory_xact_lock`` into ``auto_book_pending.py``."""

    source = (SRC / relative).read_text(encoding="utf-8")

    assert _ADVISORY.findall(source) == []


#: The names a credential travels under. ``os.environ`` alone is not one: the
#: integration support passes the environment on to ``alembic`` with a test
#: ``DATABASE_URL``.
_CREDENTIAL = re.compile(r"API_KEY|API_SECRET|MASTER_KEY|PIONEX_|BYBIT_|BINANCE_", re.IGNORECASE)


@pytest.mark.parametrize("relative", _NEW_TEST_FILES)
def test_no_new_test_file_needs_a_credential(relative: str) -> None:
    """Non-negotiable rule 1: no test may require a real API credential.
    Mutation: add ``os.environ["BYBIT_API_KEY"]`` to ``test_read_confirmed.py``."""

    source = (BACKEND / relative).read_text(encoding="utf-8")

    assert _CREDENTIAL.findall(source) == []
