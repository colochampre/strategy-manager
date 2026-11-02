"""The shape of a display name (multi-user decision 27; tasks.md F.1).

It reaches every other user, so what looks like one name must be one name: the
unique index can only tell apart what is spelled apart.
"""

import pytest

from strategy_manager.identity.domain.display_name import (
    InvalidDisplayNameError,
    normalize_display_name,
)


def test_a_name_keeps_its_case_and_its_accents() -> None:
    assert normalize_display_name("Ana Pérez") == "Ana Pérez"


def test_a_name_is_trimmed() -> None:
    assert normalize_display_name("  Ana  ") == "Ana"


def test_whitespace_inside_a_name_folds_to_one_space() -> None:
    assert normalize_display_name("Ana \t  Pérez") == "Ana Pérez"


def test_two_spellings_of_one_letter_are_one_name() -> None:
    """``e`` plus a combining accent reads as ``é``, and the index would take both."""
    assert normalize_display_name("Pérez") == "Pérez"


def test_the_length_limits_are_inclusive() -> None:
    assert normalize_display_name("Ana") == "Ana"
    assert normalize_display_name("a" * 30) == "a" * 30


@pytest.mark.parametrize("raw", ["", "   ", "An", "  An  ", "a" * 31])
def test_a_name_out_of_length_is_refused(raw: str) -> None:
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name(raw)


def test_a_name_with_an_at_sign_is_refused() -> None:
    """Nobody publishes their e-mail by accident here."""
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name("ana@example.com")


@pytest.mark.parametrize("raw", ["A​na", "Ana‮", "An\x00a", "A\x7fna"])
def test_an_invisible_character_is_refused(raw: str) -> None:
    """``A\\u200bna`` reads as ``Ana`` and passes a unique index, so it would let
    someone pass as another author."""
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "Ana️",
        "Ana︀",
        "A͏na",
        "Ana\U000e0100",
        "Ana\U000e01ef",
        "An឴a",
        "An឵a",
        "An᠋a",
        "An᠍a",
        "An᠏a",
        "ㅤㅤㅤ",
        "⠀⠀⠀",
        "ﾠﾠﾠ",
        "Anaᅟ",
        "Anaᅠ",
        "Ana Lopez\U000133fc",
        "Ana\U000133fcLopez",
        "Ana￼",
    ],
    ids=ascii,
)
def test_a_character_nobody_can_see_is_refused(raw: str) -> None:
    """Variation selectors are marks and the Hangul fillers are letters, so their
    Unicode category says nothing: each draws no ink, and ``Ana<selector>`` would pass
    the unique index beside ``Ana``."""
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "Аna Lopez",  # Cyrillic A
        "Ana Lоpez",  # Cyrillic o
        "Αna Lopez",  # Greek Alpha
        "Ana Lοpez",  # Greek omicron
        "Анα",  # Cyrillic beside Greek
        "Ana Lօpez",  # Armenian oh
        "Ꭺna Lopez",  # Cherokee A
    ],
    ids=ascii,
)
def test_a_name_that_mixes_alphabets_of_look_alike_letters_is_refused(raw: str) -> None:
    """The unique index tells these apart and a reader cannot (decision 32)."""
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name(raw)


@pytest.mark.parametrize(
    "name",
    [
        "Иван Петров",
        "Νίκος",
        "Արամ",
        "Ana 李",
        "Ana مريم",
        "Иван ✝",
        "Hawaiʻi",
        "Ana 2",
        "Иван 2",
        "田中 たなか",
    ],
)
def test_a_name_in_one_of_those_alphabets_is_kept(name: str) -> None:
    """Only letters of two of those alphabets refuse a name. A symbol called "LATIN
    CROSS" is not a letter, and a script no Latin letter can pass for may sit beside
    them."""
    assert normalize_display_name(name) == name


@pytest.mark.parametrize("name", ["Müller", "नमस्ते", "한글이름", "مريم"])
def test_a_mark_that_draws_ink_is_kept(name: str) -> None:
    """A name in a script that writes its vowels as marks stays a name: the refusal
    lists what is blank, it does not refuse every mark."""
    assert normalize_display_name(name) == name
