"""A strategy's one public capital figure (tasks.md F.4, decision 30)."""

from decimal import Decimal

from strategy_manager.performance.domain.public_capital import LiveSeat, public_capital


def _seat(share: str, balance: str | None) -> LiveSeat:
    return LiveSeat(share=Decimal(share), balance=None if balance is None else Decimal(balance))


def test_a_seat_counts_its_share_of_its_pool_balance() -> None:
    assert public_capital([_seat("30", "1000")]) == Decimal("300")


def test_the_figure_adds_every_seat() -> None:
    assert public_capital([_seat("30", "1000"), _seat("50", "200")]) == Decimal("400")


def test_a_pool_with_no_balance_read_adds_nothing() -> None:
    assert public_capital([_seat("30", "1000"), _seat("50", None)]) == Decimal("300")


def test_nobody_live_is_zero_and_not_an_absent_figure() -> None:
    assert public_capital([]) == Decimal(0)


def test_a_share_rounds_down_as_an_opening_does() -> None:
    seat = _seat("33.333333333333333333", "0.000000000000000002")

    assert public_capital([seat]) == Decimal(0)
