"""The sign-up step and the box asked again on a change
(openspec/changes/public-site, LS2, LS3, LS6).

``CompleteProfile`` takes the whole form. It refuses, storing nothing, in this
order: a country other than Argentina (the person hears that the service is not
offered to them, whatever else they typed), a field that cannot be true, a box
left unticked, a form read under versions no longer in force, and a profile
already given. Otherwise it stores the profile with both declarations dated now,
records one acceptance and commits once.

The profile is given once. The CUIT is there so that the records can name whose
trades they are (LD1), and a record whose owner can be rewritten from the panel
names nobody reliably; a correction goes through the contact address.

``AcceptLegalTerms`` is the box alone, for a user who has a profile and meets new
versions. The form is the only way in: the box without a profile is refused.

Nothing here logs a name or a CUIT.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.identity.application.ports import CommitPort
from strategy_manager.identity.domain.legal import CURRENT_VERSIONS, LegalVersions
from strategy_manager.identity.domain.profile import Profile
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignUpForm:
    first_name: str
    last_name: str
    cuit: str
    country: str
    #: "I declare that I am 18 or older".
    adult: bool
    #: "I declare that the data I give is true".
    truthful: bool
    #: "I accept the terms of service and have read the privacy policy".
    accepts: bool
    #: The versions the form was shown under.
    terms_version: str
    privacy_version: str


class DeclarationMissingError(Exception):
    """A box was left unticked; ``field`` names it as the API does."""

    def __init__(self, field: str) -> None:
        super().__init__(f"{field} must be ticked")
        self.field = field


class LegalVersionChangedError(Exception):
    """What the user ticked is not what is in force: the page predates a change."""


class ProfileAlreadyGivenError(Exception):
    pass


class ProfileMissingError(Exception):
    pass


class ProfilesPort(Protocol):
    async def give(self, user_id: UUID, profile: Profile, declared_at: datetime) -> bool:
        """Stores ``profile`` and dates both declarations, unless the user already
        has one: then nothing is written and the answer is False. One statement, so
        two forms sent at once store one profile."""
        ...

    async def has_profile(self, user_id: UUID) -> bool: ...


class AcceptancesPort(Protocol):
    async def record(
        self, user_id: UUID, versions: LegalVersions, accepted_at: datetime
    ) -> None: ...


def _check_versions(terms_version: str, privacy_version: str) -> None:
    if LegalVersions(terms=terms_version, privacy=privacy_version) != CURRENT_VERSIONS:
        raise LegalVersionChangedError("the terms or the privacy policy changed")


class CompleteProfile:
    def __init__(
        self,
        profiles: ProfilesPort,
        acceptances: AcceptancesPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._profiles = profiles
        self._acceptances = acceptances
        self._commit = commit
        self._clock = clock

    async def execute(self, user_id: UUID, form: SignUpForm) -> Profile:
        """Raises ``CountryNotServedError``, ``InvalidProfileError``,
        ``DeclarationMissingError``, ``LegalVersionChangedError`` or
        ``ProfileAlreadyGivenError``, in that order, having stored nothing. After
        the last one the caller rolls back: nothing was written, but the
        statement ran."""
        profile = Profile.of(
            first_name=form.first_name,
            last_name=form.last_name,
            cuit=form.cuit,
            country=form.country,
        )
        for field in ("adult", "truthful", "accepts"):
            if getattr(form, field) is not True:
                raise DeclarationMissingError(field)
        _check_versions(form.terms_version, form.privacy_version)

        now = self._clock.now()
        if not await self._profiles.give(user_id, profile, now):
            raise ProfileAlreadyGivenError("the profile was already given")
        await self._acceptances.record(user_id, CURRENT_VERSIONS, now)
        await self._commit.commit()
        logger.info("User %s gave their profile and accepted %s", user_id, CURRENT_VERSIONS)
        return profile


class AcceptLegalTerms:
    def __init__(
        self,
        profiles: ProfilesPort,
        acceptances: AcceptancesPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._profiles = profiles
        self._acceptances = acceptances
        self._commit = commit
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, accepts: bool, terms_version: str, privacy_version: str
    ) -> None:
        """Raises ``DeclarationMissingError``, ``LegalVersionChangedError`` or
        ``ProfileMissingError``, having recorded nothing."""
        if accepts is not True:
            raise DeclarationMissingError("accepts")
        _check_versions(terms_version, privacy_version)
        if not await self._profiles.has_profile(user_id):
            raise ProfileMissingError("the sign-up form comes first")
        await self._acceptances.record(user_id, CURRENT_VERSIONS, self._clock.now())
        await self._commit.commit()
        logger.info("User %s accepted %s again", user_id, CURRENT_VERSIONS)
