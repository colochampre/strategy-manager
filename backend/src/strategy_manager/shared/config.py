"""Application configuration.

Every value is read from the environment. Nothing here has a production-safe
default except the safety switches, which default to the safe position.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# TradingView posts webhook alerts from these four addresses only.
# https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/
TRADINGVIEW_SOURCE_IPS: frozenset[str] = frozenset(
    {
        "52.89.214.238",
        "34.212.75.30",
        "54.218.53.128",
        "52.32.178.7",
    }
)

# TradingView cancels any webhook request that takes longer than this.
# The ingress endpoint must persist the signal and return well inside it.
TRADINGVIEW_TIMEOUT_SECONDS: float = 3.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/strategy_manager"
    )

    # Safety switch. When true, no order is ever sent to a real exchange.
    # This defaults to true on purpose and must be disabled explicitly.
    dry_run: bool = True

    # Shared secret expected inside the TradingView alert JSON payload.
    # TradingView cannot sign its requests, so this plus the source-IP
    # allowlist is the whole authentication story for the webhook.
    webhook_secret: str = Field(default="")

    # Extra source addresses the webhook will accept, ON TOP of TradingView's
    # four. Empty by default, so a deployment that sets nothing behaves
    # exactly as before.
    #
    # It exists because a signal cannot be rehearsed otherwise: the alert has
    # to come from one of four fixed addresses, so nobody can send themselves
    # a test one, and the whole ingress path stays unexercised until a real
    # 4h candle closes.
    #
    # **Widening this is widening authentication.** The shared secret is still
    # required — an added address does not bypass it — but an address here is
    # one more place a request carrying a leaked secret would be accepted
    # from. Add a loopback for local rehearsal; do not add a proxy's address
    # to "make the tunnel work", because every request through a proxy carries
    # that address and the allowlist would then constrain nothing. A tunnel is
    # what ``behind_cloudflare_tunnel`` below is for.
    extra_webhook_source_ips: list[str] = Field(default_factory=list)

    # Whether this deployment sits behind a Cloudflare Tunnel. When it does,
    # the peer address is cloudflared's and the originating address arrives in
    # the ``CF-Connecting-IP`` header instead.
    #
    # A DECLARATION, never an autodetection. Cloudflare overwrites that header
    # on every request it forwards, so no client coming through the tunnel can
    # forge it — but nothing stops a client that reaches this port some other
    # way from sending one of its own. Inferring the tunnel from "is a CF
    # header present?" would trust the header on exactly the requests that did
    # not come through Cloudflare.
    #
    # Cloudflare should also be enforcing the same four addresses at the edge
    # with a WAF custom rule; this is the second copy of that judgement, on
    # the side of the tunnel that actually moves money.
    behind_cloudflare_tunnel: bool = False

    # Master key for envelope-encrypting exchange API credentials at rest.
    # 32 bytes, base64-encoded.
    master_encryption_key: str = Field(default="")

    # Pionex REST API. Spot lives under /api/v1/ and futures under /uapi/v1/
    # on this same host; they are separate base paths, not separate hosts.
    pionex_base_url: str = Field(default="https://api.pionex.com")

    # Read-only Pionex credentials, used by the balance reader only. These are
    # a development convenience: the per-account credentials that sign live
    # orders belong envelope-encrypted in the database (CLAUDE.md rule 8), not
    # in the environment.
    pionex_api_key: str = Field(default="")
    pionex_api_secret: str = Field(default="")

    # Pionex rejects a request whose timestamp is more than 20s off its clock,
    # so a read that outlives that window can never succeed on retry anyway.
    pionex_timeout_seconds: float = Field(default=10.0)

    # Bybit V5 REST API. Deliberately its OWN settings rather than a reuse of
    # the Pionex ones: two venues, two credentials, two base URLs, and one of
    # them is the only place this system can currently place a futures order.
    # Overwriting the Pionex values would also throw away the credential that
    # proved the live spot adapter works.
    #
    # ``api-testnet.bybit.com`` is a real, fully functional testnet — something
    # Pionex never offered. It is the difference between rehearsing a futures
    # order and only ever reasoning about one, so it is worth pointing at while
    # the adapter is being written.
    bybit_base_url: str = Field(default="https://api.bybit.com")

    # Read-only Bybit credentials, same standing as the Pionex pair above: a
    # development convenience for probes and balance reads. Anything that signs
    # an order loads from the envelope-encrypted vault instead
    # (CLAUDE.md rule 8).
    bybit_api_key: str = Field(default="")
    bybit_api_secret: str = Field(default="")

    bybit_timeout_seconds: float = Field(default=10.0)

    # Bybit rejects a request whose timestamp falls outside this window,
    # measured against its own clock. 5000ms is Bybit's own default and is
    # generous enough that clock skew, not latency, is what would break it.
    bybit_recv_window_ms: int = Field(default=5000)

    cors_origins: list[str] = Field(default=["http://localhost:5173"])

    # How long a PENDING/SUBMITTED reservation stays inside "active" pool
    # availability before it is excluded and eligible for sweeping.
    reservation_ttl_seconds: int = Field(default=30)

    # How long the worker sleeps between polls when it finds no claimable job.
    worker_poll_interval_seconds: float = Field(default=2.0)

    # How long execution.settle waits before asking the exchange what an
    # order became. Long enough that a market order has normally been
    # published, short enough that a reservation is not left in limbo — and
    # the job retries anyway when fills are not there yet.
    execution_settle_delay_seconds: float = Field(default=2.0)

    # How often the balance.sync job refreshes pool_balance_snapshots.
    balance_sync_interval_seconds: float = Field(default=15.0)

    # How old a snapshot may be before the allocation path refuses to size a
    # trade against it. Generous relative to the sync interval on purpose: a
    # couple of transient API failures should not halt trading, but a sync
    # chain that actually died must.
    balance_snapshot_max_age_seconds: float = Field(default=90.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
