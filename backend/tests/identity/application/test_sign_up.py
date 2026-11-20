"""``CompleteProfile`` and ``AcceptLegalTerms``: the sign-up step and the box asked
again when the terms or the policy change (openspec/changes/public-site, LS2,
LS3, LS6)."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from strategy_manager.identity.application.sign_up import (
    AcceptLegalTerms,
    CompleteProfile,
    DeclarationMissingError,
    LegalVersionChangedError,
    ProfileAlreadyGivenError,
    ProfileMissingError,
    SignUpForm,
)
from strategy_manager.identity.domain.legal import CURRENT_VERSIONS, LegalVersions
from strategy_manager.identity.domain.profile import (
    CountryNotServedError,
    InvalidProfileError,
    Profile,
)

USER_ID = uuid4()
NOW = datetime(2026, 11, 19, 15, tzinfo=UTC)
FORM = SignUpForm(
    first_name=" Ana ",
    last_name="Pérez",
    cuit="20-12345678-6",
    country="AR",
    adult=True,
    truthful=True,
    accepts=True,
    terms_version=CURRENT_VERSIONS.terms,
    privacy_version=CURRENT_VERSIONS.privacy,
)
STORED = Profile(first_name="Ana", last_name="Pérez", cuit="20123456786", country="AR")


class Profiles:
    def __init__(self, *, given: bool = False) -> None:
        self.given = given
        self.stored: list[tuple[UUID, Profile, datetime]] = []

    async def give(self, user_id: UUID, profile: Profile, declared_at: datetime) -> bool:
        if self.given:
            return False
        self.stored.append((user_id, profile, declared_at))
        return True

    async def has_profile(self, user_id: UUID) -> bool:
        return self.given


class Acceptances:
    def __init__(self) -> None:
        self.recorded: list[tuple[UUID, LegalVersions, datetime]] = []

    async def record(self, user_id: UUID, versions: LegalVersions, accepted_at: datetime) -> None:
        self.recorded.append((user_id, versions, accepted_at))


class Commit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class Clock:
    def now(self) -> datetime:
        return NOW


def _complete(profiles: Profiles, acceptances: Acceptances, commit: Commit) -> CompleteProfile:
    return CompleteProfile(profiles, acceptances, commit, Clock())  # type: ignore[arg-type]


async def test_a_whole_form_stores_the_profile_and_one_acceptance_and_commits_once() -> None:
    profiles, acceptances, commit = Profiles(), Acceptances(), Commit()

    profile = await _complete(profiles, acceptances, commit).execute(USER_ID, FORM)

    assert profile == STORED
    assert profiles.stored == [(USER_ID, STORED, NOW)]
    assert acceptances.recorded == [(USER_ID, CURRENT_VERSIONS, NOW)]
    assert commit.commits == 1


async def test_a_country_other_than_argentina_stores_nothing() -> None:
    profiles, acceptances, commit = Profiles(), Acceptances(), Commit()

    with pytest.raises(CountryNotServedError):
        await _complete(profiles, acceptances, commit).execute(USER_ID, replace(FORM, country="UY"))

    assert (profiles.stored, acceptances.recorded, commit.commits) == ([], [], 0)


async def test_a_wrong_cuit_stores_nothing_and_names_the_field() -> None:
    profiles, acceptances, commit = Profiles(), Acceptances(), Commit()

    with pytest.raises(InvalidProfileError) as refused:
        await _complete(profiles, acceptances, commit).execute(
            USER_ID, replace(FORM, cuit="20123456780")
        )

    assert refused.value.field == "cuit"
    assert (profiles.stored, acceptances.recorded, commit.commits) == ([], [], 0)


@pytest.mark.parametrize("box", ["adult", "truthful", "accepts"])
async def test_every_box_must_be_ticked(box: str) -> None:
    profiles, acceptances, commit = Profiles(), Acceptances(), Commit()

    with pytest.raises(DeclarationMissingError) as refused:
        await _complete(profiles, acceptances, commit).execute(
            USER_ID, replace(FORM, **{box: False})
        )

    assert refused.value.field == box
    assert (profiles.stored, acceptances.recorded, commit.commits) == ([], [], 0)


@pytest.mark.parametrize("stale", [{"terms_version": "old"}, {"privacy_version": "old"}])
async def test_a_form_read_under_other_versions_stores_nothing(stale: dict[str, str]) -> None:
    """The page was loaded before a change: what was ticked is not what is in force."""
    profiles, acceptances, commit = Profiles(), Acceptances(), Commit()

    with pytest.raises(LegalVersionChangedError):
        await _complete(profiles, acceptances, commit).execute(USER_ID, replace(FORM, **stale))

    assert (profiles.stored, acceptances.recorded, commit.commits) == ([], [], 0)


async def test_a_profile_is_given_once() -> None:
    profiles, acceptances, commit = Profiles(given=True), Acceptances(), Commit()

    with pytest.raises(ProfileAlreadyGivenError):
        await _complete(profiles, acceptances, commit).execute(USER_ID, FORM)

    assert (acceptances.recorded, commit.commits) == ([], 0)


def _accept(profiles: Profiles, acceptances: Acceptances, commit: Commit) -> AcceptLegalTerms:
    return AcceptLegalTerms(profiles, acceptances, commit, Clock())  # type: ignore[arg-type]


async def test_accepting_again_records_one_more_acceptance() -> None:
    profiles, acceptances, commit = Profiles(given=True), Acceptances(), Commit()

    await _accept(profiles, acceptances, commit).execute(
        USER_ID,
        accepts=True,
        terms_version=CURRENT_VERSIONS.terms,
        privacy_version=CURRENT_VERSIONS.privacy,
    )

    assert acceptances.recorded == [(USER_ID, CURRENT_VERSIONS, NOW)]
    assert commit.commits == 1


async def test_accepting_again_needs_the_box_ticked() -> None:
    profiles, acceptances, commit = Profiles(given=True), Acceptances(), Commit()

    with pytest.raises(DeclarationMissingError) as refused:
        await _accept(profiles, acceptances, commit).execute(
            USER_ID,
            accepts=False,
            terms_version=CURRENT_VERSIONS.terms,
            privacy_version=CURRENT_VERSIONS.privacy,
        )

    assert refused.value.field == "accepts"
    assert (acceptances.recorded, commit.commits) == ([], 0)


async def test_accepting_again_under_other_versions_records_nothing() -> None:
    profiles, acceptances, commit = Profiles(given=True), Acceptances(), Commit()

    with pytest.raises(LegalVersionChangedError):
        await _accept(profiles, acceptances, commit).execute(
            USER_ID, accepts=True, terms_version="old", privacy_version=CURRENT_VERSIONS.privacy
        )

    assert (acceptances.recorded, commit.commits) == ([], 0)


async def test_accepting_without_a_profile_is_refused() -> None:
    """The box alone is not a sign-up: the form records both together."""
    profiles, acceptances, commit = Profiles(given=False), Acceptances(), Commit()

    with pytest.raises(ProfileMissingError):
        await _accept(profiles, acceptances, commit).execute(
            USER_ID,
            accepts=True,
            terms_version=CURRENT_VERSIONS.terms,
            privacy_version=CURRENT_VERSIONS.privacy,
        )

    assert (acceptances.recorded, commit.commits) == ([], 0)
