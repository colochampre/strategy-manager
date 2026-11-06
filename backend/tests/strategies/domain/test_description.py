"""A strategy's description: plain text its author writes, optional, at most 2,000
characters once trimmed (decision 38). It carries the recommended configuration;
there is no separate field for a recommended leverage."""

from uuid import uuid4

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.description import (
    MAX_DESCRIPTION_LENGTH,
    description_of,
)
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy


def test_none_is_no_description() -> None:
    assert description_of(None) is None


@pytest.mark.parametrize("blank", ["", " ", "\n", "\t \r\n "])
def test_a_blank_description_is_no_description(blank: str) -> None:
    assert description_of(blank) is None


def test_it_is_trimmed_of_spaces_tabs_and_line_breaks() -> None:
    assert description_of(" \t\r\nRecommended: x3.\r\n\t ") == "Recommended: x3."


def test_only_the_four_characters_the_database_trims_are_trimmed() -> None:
    # A non-breaking space is text, as it is to ``btrim(..., E' \t\r\n')``.
    assert description_of("  x3 \n") == " x3 "


def test_the_lines_and_tabs_inside_it_are_kept() -> None:
    written = "Trades the 4h close.\n\n\tRecommended: x3,\r\nisolated."

    assert description_of(written) == written


def test_two_thousand_characters_are_taken_and_the_trim_does_not_count() -> None:
    longest = "é" * MAX_DESCRIPTION_LENGTH

    assert MAX_DESCRIPTION_LENGTH == 2000
    assert description_of(f"  {longest}\n") == longest


def test_one_more_is_refused() -> None:
    with pytest.raises(InvariantViolation, match="2000 characters"):
        description_of("x" * (MAX_DESCRIPTION_LENGTH + 1))


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f"])
def test_a_control_character_other_than_a_tab_or_a_line_break_is_refused(control: str) -> None:
    with pytest.raises(InvariantViolation, match="control character"):
        description_of(f"before{control}after")


def _strategy(description: str | None) -> Strategy:
    return Strategy(
        id=uuid4(),
        name="s",
        policy=AllocationPolicy(
            exchange=Exchange.BYBIT,
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            fill_mode=FillMode.PARTIAL,
        ),
        author_id=uuid4(),
        description=description,
    )


def test_a_strategy_has_no_description_unless_given_one() -> None:
    strategy = Strategy(
        id=uuid4(),
        name="s",
        policy=_strategy(None).policy,
        author_id=uuid4(),
    )

    assert strategy.description is None


def test_a_strategy_holds_a_trimmed_description() -> None:
    assert _strategy("Recommended: x3.").description == "Recommended: x3."


@pytest.mark.parametrize("unshaped", ["", "  padded", "trailing\n", "x" * 2001, "a\x00b"])
def test_a_strategy_refuses_a_description_not_in_its_stored_shape(unshaped: str) -> None:
    with pytest.raises(InvariantViolation, match="description"):
        _strategy(unshaped)
