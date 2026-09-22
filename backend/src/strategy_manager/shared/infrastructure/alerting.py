"""Where operator alerting is composed, and every way it stays off.

One function, used identically by both entry points. Alerting is opt-in
because the failure modes of a half-configured channel are worse than having
none: a deployment that sets nothing must behave exactly as it did before this
existed, and a deployment that sets the flag but forgets the token must say so
once and then keep running. A worker that refuses to start over its own
notification channel has made the alerting more dangerous than the silence it
was meant to end.

Nothing here needs a credential beyond the settings token — no vault, no
database, no venue — so it can be installed before anything else in startup
and still be there for the ERRORs that startup itself produces.
"""

import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.alert_log_bridge import AlertLogBridge
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.telegram_alerter import TelegramAlerter

# Inside the alerting namespace the bridge excludes, like every other part of
# this stack. Composition is where "the channel is misconfigured" is noticed,
# and a channel that is not working must not be the thing asked to report it.
logger = logging.getLogger("strategy_manager.alerts.composition")


def build_alerter(settings: Settings) -> TelegramAlerter | None:
    """The configured alerter, or ``None`` when alerting is not to run.

    Three ways of being off, and only one of them is silent. Alerting
    disabled is a choice and says nothing. Enabled with a missing token or
    chat id is a MISTAKE, and a silent one would leave an operator believing
    the phone will ring.
    """
    if not settings.alerts_enabled:
        return None

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token),
            ("TELEGRAM_CHAT_ID", settings.telegram_chat_id),
        )
        if not value
    ]
    if missing:
        # Names only. The token is a secret and never appears in a log line,
        # an error message or an alert body.
        logger.warning(
            "ALERTS_ENABLED is set but %s %s empty, so no alert can be "
            "delivered. Running without an alert channel.",
            " and ".join(missing),
            "are" if len(missing) > 1 else "is",
        )
        return None

    return TelegramAlerter(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        timeout_seconds=settings.alert_send_timeout_seconds,
    )


@asynccontextmanager
async def operator_alerts(settings: Settings) -> AsyncIterator[AlertLogBridge | None]:
    """Installs the bridge on the ROOT logger for the life of the context.

    The root logger, so every module's ERROR is covered without each one
    having to opt in: a per-logger install is a list that silently stops being
    complete the first time a module is added, and "the alert never came" is
    the exact defect this exists to prevent.

    Removal is in a ``finally`` and the alerter outlives the bridge, so the
    HTTP client is closed only after the last queued alert has been sent —
    shutdown is precisely when the ERROR worth reading tends to appear.
    """
    alerter = build_alerter(settings)
    if alerter is None:
        yield None
        return

    root = logging.getLogger()
    bridge = AlertLogBridge(
        alerter,
        clock=SystemClock(),
        throttle_window_seconds=settings.alert_throttle_window_seconds,
        # The hostname when nothing is configured, because an unlabelled alert
        # is worse than a badly labelled one: production and a developer's
        # machine write to the SAME chat, and the reader has to know which one
        # is speaking before deciding whether to act.
        deployment=settings.alert_source or socket.gethostname(),
    )
    try:
        await bridge.start()
        root.addHandler(bridge)
        logger.info(
            "operator alerts are on: ERROR and above are forwarded to Telegram, "
            "at most one per message per %.0fs",
            settings.alert_throttle_window_seconds,
        )
        yield bridge
    finally:
        root.removeHandler(bridge)
        await bridge.aclose()
        await alerter.aclose()
