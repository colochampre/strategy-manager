"""Startup invariant 4: ``ADMIN_API_TOKEN`` must be configured.

The next free number after design.md § Composition Root's three — 1 pool lock
keys, 2 ``DRY_RUN`` vs. the registered adapter, 3 the webhook secret. Same
rule as 3, applied to the other router this process mounts:
``settings.admin_api_token`` non-empty whenever the strategies router is
mounted, because an empty token makes authentication vacuous.

What this catches is silent, and silent in the opposite direction from
invariant 3. An unset webhook secret refuses everything, so the deployment at
least stops working. An unset admin token refuses everything too — but only
because ``AdminTokenAuth`` deliberately fails closed on an empty expected
value. Take that one line away and the comparison succeeds for a caller
sending nothing, and the endpoints that register strategies, arm them and set
their allocation answer the internet. Nothing logs an error; the API looks
healthy, because from its side it is. That is a failure with no symptom until
someone else's strategy is trading this account's capital.

Which is why this is a startup abort and not a warning, and why it does not
lean on the fail-closed branch being there. The invariant and the branch are
two independent reasons the hole stays shut, and an authorisation hole is
exactly the kind that should need two mistakes rather than one.

Until today this router had no authentication at all and was contained by a
path allowlist in the reverse proxy. That allowlist stays as defence in depth,
but it cannot be what closes this: it lives outside the application, and a
Caddyfile widened for an unrelated route would reopen the hole without any
change to this repository.

This is the API's half of a rule the worker already keeps. The worker refuses
to start without ``MASTER_ENCRYPTION_KEY`` rather than failing on the first
job that needs a credential; the API refuses to start without a token for the
surface that decides what gets traded.

It is deliberately NOT conditioned on ``DRY_RUN``. A dry run still writes real
strategy rows — the same rows a live process reads — so a rehearsal left open
is a production configuration left open, one environment variable later.
"""

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation


def assert_admin_api_token_configured(settings: Settings) -> None:
    if settings.admin_api_token:
        return

    raise InvariantViolation(
        "ADMIN_API_TOKEN is not set. Refusing to start: every /api "
        "endpoint authenticates on this bearer token, so an empty value makes "
        "the comparison vacuous and the only thing still keeping registration "
        "and arming off the public internet would be a reverse-proxy rule this "
        "application does not control. Generate one with: "
        'python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
