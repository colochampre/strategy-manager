"""The identity a user gives at sign-up (openspec/changes/public-site, LS2-LS3).

The CUIT is what an authority's request would name, so a number that cannot be
one is refused before anything is stored: eleven digits whose last one is the
check digit AFIP computes from the first ten.
"""

import pytest

from strategy_manager.identity.domain.profile import (
    SERVED_COUNTRY,
    CountryNotServedError,
    InvalidProfileError,
    Profile,
    normalize_cuit,
    normalize_person_name,
)


def test_a_cuit_with_its_check_digit_is_kept_as_eleven_digits() -> None:
    assert normalize_cuit("20123456786") == "20123456786"


@pytest.mark.parametrize("raw", ["20-12345678-6", " 20 12345678 6 ", "20-12345678 6"])
def test_a_cuit_may_be_written_with_hyphens_and_spaces(raw: str) -> None:
    assert normalize_cuit(raw) == "20123456786"


def test_a_check_digit_of_zero_is_valid() -> None:
    """The remainder 0 gives the digit 0, not 11."""
    assert normalize_cuit("27-30000004-0") == "27300000040"


@pytest.mark.parametrize("wrong", ["20123456780", "20123456785", "20123456787"])
def test_a_wrong_check_digit_is_refused(wrong: str) -> None:
    with pytest.raises(InvalidProfileError) as refused:
        normalize_cuit(wrong)

    assert refused.value.field == "cuit"


def test_a_number_whose_check_digit_would_be_ten_is_no_cuit() -> None:
    """AFIP never issues one: the remainder 1 has no digit, so no last digit fits."""
    for last in "0123456789":
        with pytest.raises(InvalidProfileError):
            normalize_cuit("2000000001" + last)


@pytest.mark.parametrize(
    "raw", ["", "2012345678", "201234567861", "20.12345678.6", "2O123456786", "٢٠١٢٣٤٥٦٧٨٦"]
)
def test_anything_but_eleven_ascii_digits_is_refused(raw: str) -> None:
    with pytest.raises(InvalidProfileError) as refused:
        normalize_cuit(raw)

    assert refused.value.field == "cuit"


def test_a_name_is_trimmed_and_its_inner_whitespace_folds() -> None:
    assert normalize_person_name("  María \t José ", "first_name") == "María José"


def test_a_name_keeps_its_case_its_accents_and_its_apostrophes() -> None:
    assert normalize_person_name("O'Higgins-Peña", "last_name") == "O'Higgins-Peña"


@pytest.mark.parametrize("raw", ["", "   ", "a" * 81, "Ana​", "Ana\x00"])
def test_an_empty_too_long_or_invisible_name_is_refused(raw: str) -> None:
    with pytest.raises(InvalidProfileError) as refused:
        normalize_person_name(raw, "last_name")

    assert refused.value.field == "last_name"


def test_the_longest_name_is_eighty_characters() -> None:
    assert normalize_person_name("a" * 80, "first_name") == "a" * 80


def test_a_profile_holds_the_normal_spellings() -> None:
    profile = Profile.of(
        first_name=" Ana ", last_name=" Pérez ", cuit="27-30000004-0", country="ar"
    )

    assert profile == Profile(
        first_name="Ana", last_name="Pérez", cuit="27300000040", country=SERVED_COUNTRY
    )


@pytest.mark.parametrize("country", ["US", "UY", "", "ARG"])
def test_a_country_other_than_argentina_is_not_served(country: str) -> None:
    with pytest.raises(CountryNotServedError):
        Profile.of(first_name="Ana", last_name="Pérez", cuit="20123456786", country=country)


def test_the_country_is_checked_before_the_rest() -> None:
    """Someone abroad hears that the service is not offered to them, not that a
    field of theirs is wrong: nothing else they typed matters."""
    with pytest.raises(CountryNotServedError):
        Profile.of(first_name="", last_name="", cuit="1", country="US")
