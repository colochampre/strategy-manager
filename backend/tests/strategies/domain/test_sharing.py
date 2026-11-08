"""Who may come to a strategy, and the link's token (multi-user decision 41;
tasks.md K.2).

A strategy offers itself to others by its visibility and to whoever arrives the way
that visibility admits: PUBLIC to anyone, LINK to the holder of its link, PRIVATE
to the holder of a live code. A live code also opens a LINK strategy: it was made for
this strategy, and the link would let the same person in. Nothing is offered while
the author has no name. A live seat reads its page in every mode, and that is the
public read's own rule (tasks.md J.1), not this one.
"""

import re

import pytest

from strategy_manager.strategies.domain.share_token import is_share_token, new_share_token
from strategy_manager.strategies.domain.strategy import Entry, Visibility, offered_to

# The shape ``ck_strategies_share_token_shape`` checks (migration 0038).
DB_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def test_the_visibilities_are_the_ones_the_database_takes() -> None:
    assert {member.value for member in Visibility} == {"PUBLIC", "LINK", "PRIVATE"}


@pytest.mark.parametrize(
    ("visibility", "entry", "offered"),
    [
        (Visibility.PUBLIC, Entry.NONE, True),
        (Visibility.PUBLIC, Entry.LINK, True),
        (Visibility.PUBLIC, Entry.CODE, True),
        (Visibility.LINK, Entry.NONE, False),
        (Visibility.LINK, Entry.LINK, True),
        (Visibility.LINK, Entry.CODE, True),
        (Visibility.PRIVATE, Entry.NONE, False),
        (Visibility.PRIVATE, Entry.LINK, False),
        (Visibility.PRIVATE, Entry.CODE, True),
    ],
)
def test_each_visibility_admits_its_own_entries(
    visibility: Visibility, entry: Entry, offered: bool
) -> None:
    assert offered_to(visibility, author_named=True, entry=entry) is offered


@pytest.mark.parametrize("visibility", list(Visibility))
@pytest.mark.parametrize("entry", list(Entry))
def test_nothing_is_offered_while_the_author_has_no_name(
    visibility: Visibility, entry: Entry
) -> None:
    assert offered_to(visibility, author_named=False, entry=entry) is False


def test_a_new_token_has_the_shape_the_database_checks() -> None:
    token = new_share_token()

    assert DB_TOKEN_SHAPE.fullmatch(token)
    assert is_share_token(token)


def test_two_new_tokens_differ() -> None:
    assert new_share_token() != new_share_token()


@pytest.mark.parametrize(
    "text",
    ["", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "+", "a" * 42 + "/", " " + "a" * 42],
    ids=["empty", "42", "44", "padding", "plus", "slash", "space"],
)
def test_anything_but_a_token_is_not_one(text: str) -> None:
    assert is_share_token(text) is False
