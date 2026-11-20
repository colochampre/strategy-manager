"""Whether a user may go on: a profile given, and the versions in force accepted
(openspec/changes/public-site, LS2, LS4, LS6)."""

from strategy_manager.identity.domain.legal import (
    CURRENT_VERSIONS,
    LegalVersions,
    ProfileStatus,
    profile_status,
)
from strategy_manager.identity.domain.profile import Profile

PROFILE = Profile(first_name="Ana", last_name="Pérez", cuit="20123456786", country="AR")


def test_a_profile_and_the_versions_in_force_are_complete() -> None:
    assert profile_status(PROFILE, CURRENT_VERSIONS) is ProfileStatus.COMPLETE


def test_no_profile_is_missing_whatever_was_accepted() -> None:
    assert profile_status(None, CURRENT_VERSIONS) is ProfileStatus.MISSING
    assert profile_status(None, None) is ProfileStatus.MISSING


def test_a_profile_with_no_acceptance_is_outdated() -> None:
    assert profile_status(PROFILE, None) is ProfileStatus.ACCEPTANCE_OUTDATED


def test_a_change_of_either_version_asks_again() -> None:
    older_terms = LegalVersions(terms="older", privacy=CURRENT_VERSIONS.privacy)
    older_privacy = LegalVersions(terms=CURRENT_VERSIONS.terms, privacy="older")

    assert profile_status(PROFILE, older_terms) is ProfileStatus.ACCEPTANCE_OUTDATED
    assert profile_status(PROFILE, older_privacy) is ProfileStatus.ACCEPTANCE_OUTDATED


def test_the_versions_in_force_are_named() -> None:
    assert CURRENT_VERSIONS.terms
    assert CURRENT_VERSIONS.privacy
