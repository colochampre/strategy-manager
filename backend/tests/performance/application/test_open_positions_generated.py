"""T2, the invariant over generated ledgers (design addendum "open positions",
section L).

No case table can be complete, so a few hundred ledger states are generated from
a fixed seed (``tests/performance/generated_ledger.py``): long and short
positions, a partial close, an allocation flat because its fills cancel and one
flat only because a base-currency fee shrank its purchase, three spellings of one
market, fills of either origin, and the odd symbol that cannot be split. The
guard's reader is the domain fold over those rows, exactly as the real reader
feeds it.

Asserted for every state: the answer's allocation ids EQUAL the reader's (as a
list, so a duplicated row is as visible as a dropped one) and so do its attempt
ids; every mismatch, with everything recorded in either mode, is a row of the
answer; and an empty answer is a state the guard accepts in both modes.
"""

from dataclasses import replace

import pytest

from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.domain.mode_origin import find_mismatches, fold_open_allocations
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from tests.owner import OWNER_ID
from tests.performance.fakes import (
    FakeDisagreementSource,
    FakeFactsSource,
    FakeOpenStateReader,
    NoTradeCapableKeys,
)
from tests.performance.generated_ledger import GeneratedState, generate_states

STATES = generate_states()


def test_the_generator_reaches_every_shape_the_invariant_has_to_cover() -> None:
    """The generated states are not all trivial: a test that passes over states
    that never hold anything proves nothing."""
    reader_sizes = [len(fold_open_allocations(s.ledger_groups())) for s in STATES]
    flat = sum(
        1
        for s in STATES
        for a in s.allocations
        if not fold_open_allocations(a.ledger_groups())
    )

    assert len(STATES) >= 300
    assert sum(1 for n in reader_sizes if n > 0) > 100, "too few states hold an open allocation"
    assert any(n > 1 for n in reader_sizes), "no state holds two open allocations"
    assert flat > 50, "too few allocations are flat, so the fold's exclusion is never exercised"
    assert any(s.in_flight for s in STATES)
    assert any(not a.resolves for s in STATES for a in s.allocations)
    assert any(len({f.symbol for f in a.fills}) > 1 for s in STATES for a in s.allocations)
    assert any(
        f.fee_currency.upper() == "SOL" for s in STATES for a in s.allocations for f in a.fills
    )


@pytest.mark.parametrize("state", STATES, ids=[f"state-{s.index}" for s in STATES])
async def test_the_answer_holds_the_readers_elements_one_for_one(state: GeneratedState) -> None:
    reader = FakeOpenStateReader(fold_open_allocations(state.ledger_groups()), state.in_flight)

    answer = await ReadOpenPositions(reader, FakeFactsSource(), FakeDisagreementSource()).read(
        OWNER_ID
    )

    assert [p.allocation_id for p in answer.positions] == [
        e.allocation_id for e in await reader.open_allocations()
    ], f"state {state.index}: the answer's allocation ids are not the reader's"
    assert [o.attempt_id for o in answer.orders] == [
        e.attempt_id for e in await reader.in_flight_attempts()
    ], f"state {state.index}: the answer's attempt ids are not the reader's"


@pytest.mark.parametrize("recorded", list(Mode), ids=[mode.value for mode in Mode])
@pytest.mark.parametrize("state", STATES, ids=[f"state-{s.index}" for s in STATES])
async def test_nothing_the_guard_refuses_on_is_missing_and_an_empty_answer_is_accepted(
    state: GeneratedState, recorded: Mode
) -> None:
    opened = fold_open_allocations(state.ledger_groups())
    reader = FakeOpenStateReader(
        [replace(element, mode=recorded) for element in opened],
        [replace(element, mode=recorded) for element in state.in_flight],
    )

    answer = await ReadOpenPositions(reader, FakeFactsSource(), FakeDisagreementSource()).read(
        OWNER_ID
    )

    ids = {p.allocation_id for p in answer.positions} | {o.attempt_id for o in answer.orders}
    mismatches = find_mismatches(
        open_allocations=await reader.open_allocations(),
        in_flight=await reader.in_flight_attempts(),
    )
    missing = [str(m.identifier) for m in mismatches if m.identifier not in ids]
    assert not missing, f"state {state.index}: the guard refuses on {missing}, not in the answer"

    if not answer.positions and not answer.orders:
        try:
            await assert_mode_matches_ledger(reader=reader, keys=NoTradeCapableKeys())
        except StartupRefused as refusal:
            raise AssertionError(
                f"state {state.index}: the answer is empty but the guard refuses: {refusal}"
            ) from refusal
