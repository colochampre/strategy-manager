from datetime import UTC, datetime, timedelta

from strategy_manager.shared.infrastructure.clock import SystemClock


def test_system_clock_now_is_timezone_aware_and_close_to_real_time() -> None:
    clock = SystemClock()

    now = clock.now()

    assert now.tzinfo is not None
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=2)
