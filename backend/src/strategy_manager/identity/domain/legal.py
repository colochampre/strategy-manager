"""The terms and privacy versions in force, and whether a user may go on
(openspec/changes/public-site, LS2, LS4, LS6).

The versions live here, not in the panel: ``GET /api/me`` publishes them, the
panel shows the form for them, and the server's gate compares the user's last
acceptance with them. One source, so the panel and the gate cannot disagree.
Bump one when its text changes in ``frontend/src/shared/i18n/locales``: every user
then ticks the acceptance box again before going on (LS6; LQ3 asks whether a
minor change may skip that).
"""

from dataclasses import dataclass
from enum import StrEnum

from strategy_manager.identity.domain.profile import Profile


@dataclass(frozen=True)
class LegalVersions:
    terms: str
    privacy: str


#: Drafts until the lawyer reviews them (public-site PS.11, PS.12).
CURRENT_VERSIONS = LegalVersions(terms="2026-11-19-draft-1", privacy="2026-11-20-draft-6")


class ProfileStatus(StrEnum):
    COMPLETE = "COMPLETE"
    #: The sign-up form was never sent: the whole form is asked.
    MISSING = "MISSING"
    #: The profile is there, but the versions in force were not accepted: the box
    #: alone is asked again.
    ACCEPTANCE_OUTDATED = "ACCEPTANCE_OUTDATED"


def profile_status(profile: Profile | None, accepted: LegalVersions | None) -> ProfileStatus:
    """``accepted`` is the user's latest acceptance, if any."""
    if profile is None:
        return ProfileStatus.MISSING
    if accepted != CURRENT_VERSIONS:
        return ProfileStatus.ACCEPTANCE_OUTDATED
    return ProfileStatus.COMPLETE
