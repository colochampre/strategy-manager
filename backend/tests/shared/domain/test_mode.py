"""The effective mode of an opening (multi-user design AD7): ``LIVE`` only with the
brake off and the user ``LIVE``."""

import pytest

from strategy_manager.shared.domain.mode import Mode, effective_mode


@pytest.mark.parametrize(
    ("brake", "user_mode", "expected"),
    [
        (False, Mode.LIVE, Mode.LIVE),
        (False, Mode.SIMULATION, Mode.SIMULATION),
        (True, Mode.LIVE, Mode.SIMULATION),
        (True, Mode.SIMULATION, Mode.SIMULATION),
    ],
)
def test_an_opening_is_live_only_with_the_brake_off_and_the_user_live(
    brake: bool, user_mode: Mode, expected: Mode
) -> None:
    assert effective_mode(brake=brake, user_mode=user_mode) is expected
