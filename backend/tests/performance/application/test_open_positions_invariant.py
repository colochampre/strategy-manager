"""T1, the invariant, table-driven (design addendum "open positions", section B).

The route's one promise: it answers exactly one row per element of the mode
guard's own reader, so an empty answer means the guard's two inputs were empty.
For every case of a table and for BOTH values of ``DRY_RUN``, the SAME reader
instance is given to ``find_mismatches`` and to ``ReadOpenPositions``:

* every mismatch's identifier is the id of a row of the answer; and
* when the answer is empty, ``assert_mode_matches_ledger`` does not raise.
"""

from collections.abc import Callable
from itertools import combinations
from uuid import UUID

import pytest

from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
    find_mismatches,
)
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from tests.owner import OWNER_ID
from tests.performance.fakes import FakeDisagreementSource, FakeFactsSource, FakeOpenStateReader
from tests.performance.open_state_cases import in_flight_element, open_element

Element = OpenAllocationOrigin | InFlightAttemptOrigin

KINDS: dict[str, Callable[[], Element]] = {
    "rehearsal": lambda: open_element(rehearsal=True, live=False),
    "live": lambda: open_element(rehearsal=False, live=True),
    "mixed": lambda: open_element(rehearsal=True, live=True),
    # A symbol whose base currency cannot be told from the pool's USDT: the fold
    # reports such an allocation as open rather than guess it flat.
    "unresolved": lambda: open_element(rehearsal=False, live=True, symbol="XYZBTC"),
    "rehearsal order": lambda: in_flight_element(rehearsal=True),
    "live order": lambda: in_flight_element(rehearsal=False),
}

CASES: dict[str, tuple[str, ...]] = {
    "nothing": (),
    **{kind: (kind,) for kind in KINDS},
    **{f"{a} + {b}": (a, b) for a, b in combinations(KINDS, 2)},
}


def _reader(kinds: tuple[str, ...]) -> FakeOpenStateReader:
    opened: list[OpenAllocationOrigin] = []
    in_flight: list[InFlightAttemptOrigin] = []
    for kind in kinds:
        element = KINDS[kind]()
        if isinstance(element, OpenAllocationOrigin):
            opened.append(element)
        else:
            in_flight.append(element)
    return FakeOpenStateReader(opened, in_flight)


def _use_case(reader: FakeOpenStateReader) -> ReadOpenPositions:
    return ReadOpenPositions(reader, FakeFactsSource(), FakeDisagreementSource())


@pytest.mark.parametrize("dry_run", [True, False], ids=["DRY_RUN=true", "DRY_RUN=false"])
@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
async def test_every_mismatch_the_guard_would_refuse_on_is_a_row_of_the_answer(
    case: str, dry_run: bool
) -> None:
    reader = _reader(CASES[case])

    answer = await _use_case(reader).read(OWNER_ID)

    ids: set[UUID] = {p.allocation_id for p in answer.positions} | {
        o.attempt_id for o in answer.orders
    }
    mismatches = find_mismatches(
        dry_run=dry_run,
        open_allocations=await reader.open_allocations(),
        in_flight=await reader.in_flight_attempts(),
    )
    missing = [m for m in mismatches if m.identifier not in ids]
    assert not missing, (
        f"the guard refuses on {[str(m.identifier) for m in missing]} "
        f"(case {case!r}, DRY_RUN={dry_run}) and the answer holds {sorted(map(str, ids))}"
    )


@pytest.mark.parametrize("dry_run", [True, False], ids=["DRY_RUN=true", "DRY_RUN=false"])
@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
async def test_an_empty_answer_is_a_state_the_guard_accepts_in_both_modes(
    case: str, dry_run: bool
) -> None:
    reader = _reader(CASES[case])

    answer = await _use_case(reader).read(OWNER_ID)

    if not answer.positions and not answer.orders:
        # The guard raises StartupRefused when it would refuse: the assertion is
        # that it does not.
        try:
            await assert_mode_matches_ledger(dry_run=dry_run, reader=reader)
        except StartupRefused as refusal:
            raise AssertionError(
                f"the answer is empty (case {case!r}) but the guard refuses to start "
                f"with DRY_RUN={dry_run}: {refusal}"
            ) from refusal
    else:
        assert case != "nothing", "an empty ledger must be answered empty"


async def test_the_answer_for_an_empty_reader_is_empty() -> None:
    answer = await _use_case(_reader(())).read(OWNER_ID)

    assert (answer.positions, answer.orders) == ((), ())
