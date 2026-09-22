"""``HttpHeartbeat``: the outbound half of the dead-man's switch.

The watchdog (``shared.application.watchdog``) answers four questions about
this deployment and reports by logging. Both of those depend on the worker
still claiming jobs. If the process dies, or its claim loop stops, the checks
stop running and the ERROR bridge has nothing to forward — the silence is
indistinguishable from health, which is the original defect the watchdog was
written for, one level up.

So the last signal has to leave the deployment. Something outside it expects a
ping on a cadence and escalates when one stops arriving; the escalation is then
driven by ABSENCE, which is the only mechanism a dead process cannot suppress.

**Provider-agnostic on purpose.** healthchecks.io, Better Stack, Cronitor and a
dozen lines of self-hosted cron receiver all expose the same thing: an opaque
URL that means "I am still here" when it is requested. One setting holding one
URL fits all of them and commits this system to none of them, and there is no
payload to agree on because the service reads the arrival, not the body.

**The URL is a CREDENTIAL.** The token is in the PATH — that is exactly the
shape of a healthchecks.io ping URL — so there is no header and no query to
strip, and anyone holding it can forge the heartbeat, which turns the switch
off without turning anything red. It is never logged, never put in a message
and never carried into an alert. ``alert_redaction.redact`` does NOT cover this
shape (it strips a URL's QUERY, and this URL has none), so the scrubbing here
is by exact match on the URL and on its path, and ``redact`` is only a second
line behind that.

**It never raises, and it never logs an ERROR.** Not raising is for the chain:
the watchdog is the one recurring job nothing else is watching, so an
unreachable monitoring endpoint must not be able to spend its retries. Not
logging an ERROR is for the phone: ERROR is what ``AlertLogBridge`` forwards,
and a heartbeat failure is a monitoring outage — paging the owner about the
monitoring is the same loop the bridge excludes the alerter's own namespace to
prevent. A failure here is a WARNING and nothing else, under that same excluded
namespace, for both reasons at once.
"""

import logging
from types import TracebackType
from urllib.parse import urlsplit

import httpx

from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.alert_redaction import redact

# Must stay inside ``alert_log_bridge.EXCLUDED_LOGGER_PREFIXES[0]``, like
# ``telegram_alerter``'s, and for the same reason: the components that report a
# failure to notify must not themselves be able to request a notification. Not
# imported from there — the adapter has no business knowing the bridge exists.
# The invariant is pinned by a test instead.
logger = logging.getLogger("strategy_manager.alerts.heartbeat")

_REDACTED = "<REDACTED>"


class HttpHeartbeat:
    """A ``HeartbeatPort`` backed by a plain GET to an opaque URL."""

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._path = urlsplit(url).path
        self._timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    @property
    def url(self) -> str:
        """For composition and its tests only. Nothing may log this."""
        return self._url

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def ping(self) -> None:
        """One GET, bounded by the configured timeout, and quiet when it works.

        GET rather than POST because every provider accepts it and none of them
        needs a body; a heartbeat that had to agree on a payload would not be
        provider-agnostic. Redirects are not followed: a ping URL that has
        started redirecting is a misconfiguration worth a WARNING, not a second
        request to somewhere nobody configured.
        """
        try:
            response = await self._http.get(self._url)
        except Exception as exc:
            self._report(f"{type(exc).__name__}: {exc}")
            return

        if not response.is_success:
            self._report(f"the heartbeat endpoint answered HTTP {response.status_code}")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "HttpHeartbeat":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _report(self, detail: str) -> None:
        """httpx names the request URL inside its own exception messages, and
        this adapter's URL IS the secret. Scrubbed by exact match on the whole
        URL and again on its path alone — some errors quote only the path —
        before ``redact`` gets a second pass at whatever else is in there."""
        scrubbed = detail.replace(self._url, _REDACTED)
        if self._path:
            scrubbed = scrubbed.replace(self._path, f"/{_REDACTED}")
        logger.warning("could not send the watchdog heartbeat: %s", redact(scrubbed))


def build_heartbeat(settings: Settings) -> HttpHeartbeat | None:
    """The configured heartbeat, or ``None`` when the feature is off.

    Empty is off, and off is SILENT — not a warning, not a degraded mode. There
    is no half-configured state to complain about the way ``build_alerter`` has
    one: a URL is the entire configuration, so either there is one or the
    feature was never asked for, and a deployment that sets nothing behaves
    exactly as it did before this existed.

    Stripped, because a URL pasted into a ``.env`` with a trailing space would
    otherwise become a request to a host that does not exist, once per watchdog
    interval, forever, reported only as a WARNING nobody is watching for.
    """
    url = settings.watchdog_heartbeat_url.strip()
    if not url:
        return None

    return HttpHeartbeat(
        url=url,
        timeout_seconds=settings.watchdog_heartbeat_timeout_seconds,
    )
