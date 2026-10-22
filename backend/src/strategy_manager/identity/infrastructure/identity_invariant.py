"""Startup invariant: the API knows who is signed in, and who the admin is
(multi-user design AD1).

It replaces the bearer-token invariant (startup invariant 4), and keeps its
reason: a misconfiguration here fails with no symptom. An API with no identity
source would refuse every panel request, which at least shows; an API whose dev
identity survived into a live deployment would sign every request in as that
user, and nothing would log it.

So each of these is a startup abort, not a warning:

- no ``ADMIN_EMAIL``, or one that is not an address: nobody could reach
  Discrepancies, and the users list would have no owner;
- half an Access configuration: the verifier would accept tokens for the wrong
  audience or issuer, or none at all;
- no identity source at all;
- ``DEV_USER_EMAIL`` beside Access, which would make the source ambiguous;
- ``DEV_USER_EMAIL`` while ``DRY_RUN`` is false.

The messages name settings, never their values.
"""

from strategy_manager.identity.domain.user import InvalidEmailError, normalize_email
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation


def assert_identity_configured(settings: Settings) -> None:
    if not _is_address(settings.admin_email):
        raise InvariantViolation(
            "ADMIN_EMAIL is not set to an e-mail address. Refusing to start: the "
            "admin is the user signed in with that address, and without it nobody "
            "can reach the admin views."
        )

    has_team = bool(settings.access_team_domain.strip())
    has_aud = bool(settings.access_aud.strip())
    if has_team != has_aud:
        raise InvariantViolation(
            "ACCESS_TEAM_DOMAIN and ACCESS_AUD must be set together. Refusing to "
            "start: with only one of them the Access assertion cannot be checked "
            "against both its issuer and its audience."
        )

    dev = settings.dev_user_email
    if dev and has_team:
        raise InvariantViolation(
            "DEV_USER_EMAIL is set beside ACCESS_TEAM_DOMAIN and ACCESS_AUD. Refusing "
            "to start: the signed-in user would depend on which one wins. Remove "
            "DEV_USER_EMAIL; it is for local runs without Cloudflare only."
        )
    if dev and not settings.dry_run:
        raise InvariantViolation(
            "DEV_USER_EMAIL is set while DRY_RUN is false. Refusing to start: every "
            "request would be signed in as that user on a live deployment. Remove "
            "DEV_USER_EMAIL; it is for local runs without Cloudflare only."
        )
    if dev and not _is_address(dev):
        raise InvariantViolation("DEV_USER_EMAIL is not an e-mail address. Refusing to start.")

    if not has_team and not dev:
        raise InvariantViolation(
            "Neither ACCESS_TEAM_DOMAIN and ACCESS_AUD nor DEV_USER_EMAIL is set. "
            "Refusing to start: no request could be signed in. In production set the "
            "two Access values from Zero Trust; for a local run set DEV_USER_EMAIL."
        )


def _is_address(value: str) -> bool:
    try:
        normalize_email(value)
    except InvalidEmailError:
        return False
    return True
