"""Startup invariant 3: ``WEBHOOK_SECRET`` must be configured.

Specified by design.md § Composition Root, invariant 3 — "``settings.webhook_secret``
non-empty whenever the signals router is mounted", because "an empty secret
makes authentication vacuous".

What this catches is silent, which is why it is worth a startup abort. With no
secret configured the API starts, the router mounts, the endpoint answers, and
``SourceIpAndSecretAuth`` fails closed on every request — so every TradingView
alert is answered 401 and dropped. Nothing in the deployment reports itself as
broken. The symptom is signals that never arrive, which is indistinguishable
from a strategy that never fired, and by the time anyone looks the alerts are
gone: TradingView does not replay them.

This is the API's half of a rule the worker already keeps. The worker refuses
to start without ``MASTER_ENCRYPTION_KEY`` rather than failing on the first job
that needs a credential; the API refuses to start without ``WEBHOOK_SECRET``
rather than failing on the first alert that needs authenticating. A process
that cannot do its job should say so at boot, not at the first request.

It is deliberately NOT conditioned on ``DRY_RUN``. A dry run still ingests
signals — that is most of what a dry run is for — so an empty secret breaks a
rehearsal exactly as thoroughly as it breaks production.
"""

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation


def assert_webhook_secret_configured(settings: Settings) -> None:
    if settings.webhook_secret:
        return

    raise InvariantViolation(
        "WEBHOOK_SECRET is not set. Refusing to start: the webhook authenticates "
        "on source IP AND shared secret, so an empty secret makes the comparison "
        "vacuous and every TradingView alert would be answered 401 — signal loss "
        "that looks exactly like a strategy that never fired. Generate one with: "
        'python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
