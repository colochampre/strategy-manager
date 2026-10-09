"""The startup line of ``WEBHOOK_PUBLIC_ORIGIN`` (design.md, unit 12f addendum,
sections F and J).

The setting is display only: the panel shows and copies the webhook's full URL
from it. So the check is a LINE and never a refusal.

| Setting | Line |
| --- | --- |
| unset | INFO: the panel shows the path only |
| well formed | INFO with the normalised origin |
| malformed | ERROR naming the setting and a fixed reason; the API starts; the route says ``null`` |

The malformed case is ERROR, not WARNING, because on screen it cannot be told
from the unset one and only ERROR reaches the alert channel.

**It is deliberately NOT a startup invariant.** The process that would refuse to
start is the one that receives the alerts (rule 3); a typo in a display setting
must not cost a signal. So this function never raises.

**The raw value is never logged.** It may be refused exactly because it holds a
credential, so the ERROR carries the setting's NAME and the parser's fixed
reason, nothing the sender typed.
"""

import logging

from strategy_manager.shared.config import Settings
from strategy_manager.signals.domain.webhook_origin import (
    InvalidWebhookOrigin,
    parse_webhook_origin,
)

logger = logging.getLogger(__name__)


def log_webhook_origin(settings: Settings) -> None:
    """Logs exactly one line about ``settings.webhook_public_origin``; never
    raises."""
    try:
        origin = parse_webhook_origin(settings.webhook_public_origin)
    except InvalidWebhookOrigin as exc:
        logger.error(
            "WEBHOOK_PUBLIC_ORIGIN is malformed (%s): the panel shows the webhook path only",
            exc,
        )
        return
    if origin is None:
        logger.info("WEBHOOK_PUBLIC_ORIGIN is not set: the panel shows the webhook path only")
        return
    logger.info("WEBHOOK_PUBLIC_ORIGIN is set: the panel builds the webhook URL on %s", origin)
