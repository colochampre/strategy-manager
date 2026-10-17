"""Scenarios of the PR 15 specs that design § L does not name as a test, each
its own pin (cd.1.34, as op.1.28 did for PR 14): the confirmed-discrepancies
backend adds no migration, stays inside ``reconciliation``, ``main.py`` and
the config, touches no mode-guard file, takes no pool advisory lock in its new
code and needs no credential in its new tests.

They pass at once; each is proven by a mutation named in its docstring.

The ``git`` pins compare with ``main`` and are skipped when ``git`` or the
``main`` ref is not there (a CI checkout without history); once this branch is
merged the diff is empty and they hold trivially, which is the point of a
scope pin that guards a unit and not the future.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SRC = BACKEND / "src" / "strategy_manager"

#: The migration head before this unit. A later unit that adds a migration
#: updates this line on purpose; the pin exists so that THIS unit cannot.
BASE_HEAD = "0028"

#: The mode guard's own files (design § A: the DRY_RUN guard the open
#: positions read iterates over) plus the signal-side holding guard.
_GUARD_FILES = (
    "backend/src/strategy_manager/signals/application/holding_guard.py",
    "backend/src/strategy_manager/execution/domain/fill.py",
    "backend/src/strategy_manager/execution/application/ports.py",
)

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


def _git(*args: str) -> str:
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    done = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        pytest.skip(f"git {' '.join(args)} failed: {done.stderr.strip()[:120]}")
    return done.stdout


def _changed_files() -> list[str]:
    return [line for line in _git("diff", "--name-only", "main...HEAD").splitlines() if line]


def test_the_migration_head_is_the_one_before_the_unit() -> None:
    """Mutation: add any migration file with a new revision."""

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))

    assert ScriptDirectory.from_config(config).get_heads() == [BASE_HEAD]


def test_the_unit_adds_no_migration_file() -> None:
    changed = [name for name in _changed_files() if name.startswith("backend/migrations/")]

    assert changed == []


def test_the_diff_stays_inside_reconciliation_main_config_and_tests() -> None:
    """Spec "The diff stays inside reconciliation, main.py and config".
    Mutation: touch any other module's source file."""

    allowed_prefixes = (
        "backend/src/strategy_manager/reconciliation/",
        "backend/tests/",
        "openspec/",
        "frontend/",
        ".atl/",
    )
    allowed_files = {
        "backend/src/strategy_manager/main.py",
        "backend/src/strategy_manager/shared/config.py",
    }
    stray = [
        name
        for name in _changed_files()
        if not name.startswith(allowed_prefixes) and name not in allowed_files
    ]

    assert stray == []


def test_no_mode_guard_file_is_changed() -> None:
    """Mutation: touch ``holding_guard.py``."""

    changed = set(_changed_files())

    assert [name for name in _GUARD_FILES if name in changed] == []


def test_main_py_only_gains_reconciliation_wiring() -> None:
    """``main.py`` removes no line and every import it adds is the
    reconciliation module's. Mutation: delete any line of ``main.py``, or add
    an import from another module."""

    out = _git("diff", "--numstat", "main...HEAD", "--", "backend/src/strategy_manager/main.py")
    if not out.strip():
        return
    _added, deleted, _name = out.split()[:3]
    assert deleted == "0"

    diff = _git("diff", "-U0", "main...HEAD", "--", "backend/src/strategy_manager/main.py")
    added_imports = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+from strategy_manager.") or line.startswith("+import ")
    ]
    assert added_imports  # the pin is not vacuous: the handler's wiring adds some
    assert [i for i in added_imports if "strategy_manager.reconciliation." not in i] == []


def test_the_dotenv_credentials_test_is_unchanged() -> None:
    """Mutation: edit ``tests/shared/test_no_dotenv_credentials.py``."""

    changed = _changed_files()

    assert "backend/tests/shared/test_no_dotenv_credentials.py" not in changed
    assert (BACKEND / "tests" / "shared" / "test_no_dotenv_credentials.py").is_file()


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
