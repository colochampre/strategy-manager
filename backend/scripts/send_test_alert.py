"""Manual check: does an ERROR in this deployment actually reach a phone?

This is NOT a test. It needs a real bot token and it talks to Telegram, which
is why it lives here and not under tests/ (CLAUDE.md rule 1).

It exercises the REAL path, not just the HTTP call: an ERROR is logged through
an ordinary logger, and everything the worker would do to it — the bridge, the
queue, the throttle, the redaction, the Bot API call — happens exactly as it
would in production. A probe that only posted to the Bot API would prove the
token works and leave the wiring unverified, which is the half that actually
broke.

The alerter swallows its own failures by design, so this script watches the
alerting logger instead and reports what it saw. Exit code 0 means the message
was accepted by Telegram; 1 means it was not, and the reason is printed.

Prints no secret. The bot token is rendered as its last four characters at
most, the same standing the credential scripts give an exchange key.

Usage:
    cd backend
    # ALERTS_ENABLED, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set
    uv run python scripts/send_test_alert.py
    uv run python scripts/send_test_alert.py --message "deploy 2026-09-22"
"""

import argparse
import asyncio
import logging
import sys

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.alerting import operator_alerts

SOURCE_LOGGER = "strategy_manager.scripts.send_test_alert"


class DeliveryWatch(logging.Handler):
    """Collects what the alerting stack said about its own delivery.

    ``TelegramAlerter`` never raises — it runs behind work that is already
    failing — so a WARNING under its namespace is the only evidence that a
    send did not land.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.failures: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("strategy_manager.alerts"):
            self.failures.append(record.getMessage())


def _describe(settings: Settings) -> None:
    token = settings.telegram_bot_token
    print(f"ALERTS_ENABLED           {settings.alerts_enabled}")
    print(f"TELEGRAM_BOT_TOKEN       {'***' + token[-4:] if token else '(not set)'}")
    print(f"TELEGRAM_CHAT_ID         {settings.telegram_chat_id or '(not set)'}")
    print(f"send timeout             {settings.alert_send_timeout_seconds}s")
    print(f"throttle window          {settings.alert_throttle_window_seconds}s")
    print(f"DRY_RUN                  {settings.dry_run}  (alerting ignores it)")


async def _run(message: str, settings: Settings) -> int:
    watch = DeliveryWatch()
    root = logging.getLogger()
    root.addHandler(watch)
    try:
        async with operator_alerts(settings) as bridge:
            if bridge is None:
                print(
                    "\nNo alert channel was installed. Set ALERTS_ENABLED=true and "
                    "supply both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
                )
                return 1

            print("\nLogging one ERROR through the ordinary logging stack...")
            logging.getLogger(SOURCE_LOGGER).error(
                "alert channel test: %s", message
            )
            await bridge.drain()
            dropped = bridge.dropped
    finally:
        root.removeHandler(watch)

    if dropped:
        print(f"FAILED  {dropped} alert(s) were dropped before reaching Telegram.")
        return 1
    if watch.failures:
        print("FAILED  Telegram did not accept the message:")
        for failure in watch.failures:
            print(f"  {failure}")
        return 1

    print("OK      Telegram accepted the message. Check the chat.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--message",
        default="if you can read this, ERROR-level alerting works",
        help="what the test alert should say",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    settings = get_settings()
    _describe(settings)

    return await _run(args.message, settings)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
