"""Delivers an alert to a Telegram chat over the Bot API.

Telegram, and not email or SMS: it needs no relay to own, no outbound port
beyond 443, and it arrives on a phone as a notification rather than as another
inbox row. One bot token and one chat id is the whole configuration.

**This adapter never raises out of ``send``.** It runs behind work that is
already in trouble — the alert is about a failure — so a raise here would turn
one outage into two and spend the job's retry budget on the messenger. A
failure to deliver is logged at WARNING and swallowed.

WARNING, specifically, and under the alerting namespace, specifically: ERROR
is the level ``AlertLogBridge`` forwards, and this module's logger is inside
the namespace that bridge excludes. Both are the same rule from two sides —
the thing that reports a failure to alert must not itself be able to request
an alert.
"""

import logging
from types import TracebackType

import httpx

from strategy_manager.shared.infrastructure.alert_redaction import redact

# Telegram rejects a ``sendMessage`` whose text is longer than this outright,
# so an untruncated alert about a big failure is no alert at all.
TELEGRAM_TEXT_LIMIT = 4096

TELEGRAM_BASE_URL = "https://api.telegram.org"

_TRUNCATION_MARKER = "\n… [truncated]"

# Must stay inside ``alert_log_bridge.EXCLUDED_LOGGER_PREFIXES[0]``. Not
# imported from there: the adapter has no business knowing the bridge exists.
# The invariant is pinned by a test instead.
logger = logging.getLogger("strategy_manager.alerts.telegram")


class TelegramAlerter:
    """An ``AlertPort`` backed by the Telegram Bot API."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds
        # One client for the life of the bridge rather than one per alert: an
        # alert storm is exactly when a fresh TLS handshake per message would
        # cost the most, and the drain task sends them one at a time anyway.
        self._http = httpx.AsyncClient(
            base_url=TELEGRAM_BASE_URL,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def send(self, title: str, body: str) -> None:
        text = _truncate(redact(f"{title}\n\n{body}" if body else title))
        try:
            response = await self._http.post(
                # The token rides in the PATH. Nothing here may log this URL.
                f"/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    # No ``parse_mode``: a log line is arbitrary text, and any
                    # markup mode turns an underscore or a backtick in it into
                    # an escape sequence Telegram then rejects. Plain text has
                    # no escape syntax, so truncation cannot cut one in half.
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            self._report(f"{type(exc).__name__}: {exc}")
            return

        if response.status_code != httpx.codes.OK:
            self._report(f"Telegram answered HTTP {response.status_code}")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "TelegramAlerter":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _report(self, detail: str) -> None:
        """httpx puts the request URL inside its own exception messages, and
        this adapter's token is part of that URL. The token is scrubbed by
        exact match first — ``redact``'s shape-based rules are a second line,
        not the first — so an outage cannot publish the alerting credential
        into the log it was meant to escape."""
        logger.warning(
            "could not deliver an alert to Telegram: %s",
            redact(detail.replace(self._token, "<REDACTED>")),
        )


def _truncate(text: str) -> str:
    """Cuts on a code-point boundary, and on whitespace where one is near.

    Python strings are sequences of code points, so a slice can never land
    inside a character's own UTF-8 encoding. Preferring a whitespace boundary
    is about legibility: a body cut mid-token reads as corruption.
    """
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return text

    keep = TELEGRAM_TEXT_LIMIT - len(_TRUNCATION_MARKER)
    head = text[:keep]
    boundary = head.rfind("\n")
    if boundary < keep - 200:
        boundary = head.rfind(" ")
    if boundary >= keep - 200:
        head = head[:boundary]
    return head + _TRUNCATION_MARKER
