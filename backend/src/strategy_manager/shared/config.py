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

    # Binance REST API. Two hosts, one signing scheme: USDⓈ-M futures lives on
    # fapi.binance.com, and spot plus the account-wide wallet endpoints live on
    # api.binance.com. Binance segregates wallets like Pionex, so a futures
    # pool reads only the USDⓈ-M futures wallet.
    binance_futures_base_url: str = Field(default="https://fapi.binance.com")
    binance_spot_base_url: str = Field(default="https://api.binance.com")

    # Read-only Binance credentials, same standing as the Bybit and Pionex
    # pairs above: probes and balance reads only. A key that signs orders loads
    # from the envelope-encrypted vault (CLAUDE.md rule 8).
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")

    binance_timeout_seconds: float = Field(default=10.0)

    # Binance rejects a timestamp 1000ms or more ahead of its clock, or older
    # than this window. 5000ms is Binance's own default; 60000ms its ceiling.
    binance_recv_window_ms: int = Field(default=5000)

    # Bearer token required by every ``/strategies`` endpoint — the surface
    # that registers strategies and arms them, which is to say the surface
    # that decides what this system trades and with how much capital.
    #
    # There is no safe default, and an empty value is not one. It is empty
    # here so that a deployment which sets nothing is REFUSED at startup
    # (invariant 4) rather than served; a placeholder default would be a
    # published password, and a "disable auth when empty" fallback would hand
    # the internet the admin API the moment this line went unread.
    #
    # Unlike ``webhook_secret`` this is a token WE issue to ourselves: no
    # third party's request format constrains it, so it travels in the
    # ``Authorization`` header rather than a query string and never reaches
    # the access log.
    admin_api_token: str = Field(default="")

    cors_origins: list[str] = Field(default=["http://localhost:5173"])

    # How long a PENDING/SUBMITTED reservation stays inside "active" pool
    # availability before it is excluded and eligible for sweeping.
    reservation_ttl_seconds: int = Field(default=30)

    # How long the worker sleeps between polls when it finds no claimable job.
    #
    # This is a POLLING cadence and nothing else. It used to be handed to
    # ``SweepHandler`` as its scheduling interval too; see the setting below
    # for what that cost.
    worker_poll_interval_seconds: float = Field(default=2.0)

    # How often reservation.sweep gives expired reservations a terminal status.
    #
    # Bookkeeping cadence, not a correctness one: ``sum_active`` already
    # excludes reservations past ``expires_at``, so capital is released from
    # pool availability whether or not the sweep has run
    # (``expire_reservations.py``'s own docstring). What the sweep buys is that
    # an orphaned reservation stops being indistinguishable from one still
    # being worked on — an observability property, and 60s is fast enough for
    # a human reading the table.
    #
    # It exists as its OWN setting because it used to be
    # ``worker_poll_interval_seconds`` (2.0s) reused as a scheduling interval.
    # One poll of an empty queue is one cheap indexed SELECT; one sweep is a
    # job ROW, written and later marked DONE. At 2s that chain alone wrote
    # ~43,200 rows a day — 83% of everything this system enqueued — for
    # bookkeeping nothing waits on. At 60s it writes 1,440.
    reservation_sweep_interval_seconds: float = Field(default=60.0)

    # How long execution.settle waits before asking the exchange what an
    # order became. Long enough that a market order has normally been
    # published, short enough that a reservation is not left in limbo — and
    # the job retries anyway when fills are not there yet.
    execution_settle_delay_seconds: float = Field(default=2.0)

    # How often the balance.sync job refreshes pool_balance_snapshots.
    #
    # Raised from 15s to 60s (design.md § S3, on-demand refresh): the periodic
    # sync no longer has to catch a stale balance before an opening signal is
    # sized -- ``RefreshPoolBalance`` does that on demand, right before the
    # advisory lock, and the sync only has to keep the heartbeat alive for the
    # cases nothing signals on (a strategy that never trades, closing-only
    # traffic). It MUST stay under ``balance_snapshot_max_age_seconds`` below,
    # or a snapshot could go straight from fresh to UNAVAILABLE with no window
    # where an on-demand refresh failure could still fall back to it.
    balance_sync_interval_seconds: float = Field(default=60.0)

    # How old a snapshot may be before the allocation path refuses to size a
    # trade against it. Generous relative to the sync interval on purpose: a
    # couple of transient API failures should not halt trading, but a sync
    # chain that actually died must. Also the bound ``RefreshPoolBalance``
    # (design.md § S3) uses to decide FALLBACK vs UNAVAILABLE when the
    # on-demand refresh itself fails -- the same number, because both are
    # answering the same question: is the last known balance still trustworthy?
    balance_snapshot_max_age_seconds: float = Field(default=90.0)

    # How long ``RefreshPoolBalance`` waits for the on-demand, pre-allocation
    # balance read before giving up and falling back to the stored snapshot
    # (design.md § S3). Shorter than the venue client's own timeout on
    # purpose: a signal must not be held hostage by a socket that hangs past
    # the point where the fallback path would already have answered.
    balance_refresh_timeout_seconds: float = Field(default=3.0)

    # How long ``VenueNetPositionAdapter`` waits for the Existing-Position
    # Guard's divergent-branch venue read (design.md § S4) -- the last remote
    # call this guard makes, before the pool's advisory lock. ANY failure or
    # timeout degrades to AMBIGUOUS rather than raising, so this bound only
    # decides how long a divergent signal waits before that refusal, not
    # whether one happens.
    venue_net_position_timeout_seconds: float = Field(default=3.0)

    # The owner's number (2026-09-21): the longest an opening signal may be
    # delayed waiting for in-flight work on the same strategy/symbol to
    # settle before ``HoldingGuard`` gives up and abandons it with a WARNING
    # instead of retrying forever. Covers settlement plus a refresh retry; on
    # the owner's 4-hour bars that is under 5% of a candle. Reused unchanged
    # by the S5 continuation's own abandonment bound.
    delayed_open_max_signal_age_seconds: float = Field(default=600.0)

    # How long the S5 continuation (``signal.open_after_close``, design.md §
    # S5) waits, from an awaited close's ``created_at``, before abandoning
    # with an ERROR instead of polling forever for a close that never
    # settles. A close usually settles in seconds; this is the ceiling for
    # "the exchange never answered", not the expected wait.
    open_after_close_settle_timeout_seconds: float = Field(default=300.0)

    # How often the S5 continuation re-polls the database (never the venue)
    # to check whether every awaited close has settled (design.md § S5).
    # Deliberately NOT the failure backoff (30/60/120/240/480s, ``fail()``
    # above) -- a fill usually lands in ~2s, and the first backoff step alone
    # would hold a signal hostage for 30s after a fill that already landed.
    open_after_close_poll_interval_seconds: float = Field(default=5.0)

    # How often reconciliation.scan compares each pool's venue-reported net
    # position against the ledger's.
    #
    # Measured, not guessed (Phase 0, scripts/measure_reconciliation_rate_limits.py,
    # run live against both venues on 2026-09-18): Binance's REQUEST_WEIGHT
    # ceiling, read back from /fapi/v1/exchangeInfo, is 2400/min; a
    # no-symbol /fapi/v3/positionRisk call costs 5 weight, the same as
    # balance.sync's own /fapi/v3/account. At this interval that is 10
    # weight/min against the 480 (20%) polling allowance — about 2%, nowhere
    # near binding. Bybit's /v5/position/list and /v5/account/wallet-balance
    # do not share a bucket either (X-Bapi-Limit-Status held at 49 across
    # three probe calls). The tightest rate-limit floor either venue implied
    # was 0.7s, so rate limits did not choose 30 — staleness tolerance and the
    # false-confirmation floor did: confirmation needs
    # reconciliation_confirmations consecutive scans, so detection latency is
    # roughly 2x this interval (~60s), and 30s keeps both scans well outside
    # any settlement window.
    reconciliation_scan_interval_seconds: float = Field(default=30.0)

    # How many consecutive scans must see the same discrepancy before it is
    # confirmed rather than dismissed as a transient read (e.g. a fill still
    # settling on the venue). Chosen in design, not measured like the
    # interval above: two catches a real drift within one extra scan while
    # refusing to confirm off a single noisy read.
    reconciliation_confirmations: int = Field(default=2)

    # --- Operator alerting --------------------------------------------------
    #
    # Every ERROR this process logs is forwarded to a Telegram chat. It exists
    # because the log was the only signal and nobody reads one that is quiet
    # 99% of the time: ``balance.sync`` was dead for three days in production,
    # warning on every retry, and the deployment stopped learning its own
    # capital while looking alive.
    #
    # OFF by default and turned on explicitly. When it is off the bridge is
    # never installed, so an existing deployment that sets nothing behaves
    # exactly as it did — and a half-configured one cannot start posting into
    # an empty chat id. Alerts fire regardless of DRY_RUN: this is about the
    # system's health, not about whether it is trading.
    alerts_enabled: bool = False

    # Bot token from @BotFather. A SECRET, and one that travels in the request
    # PATH rather than a header, so nothing may log the alerter's URL
    # (telegram_alerter.py). No default: a default would be a published
    # credential, and a default chat id would be somebody else's phone.
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # How long one alert may spend on the wire. The drain task sends one at a
    # time, so this bounds how long a hung socket holds every later ERROR
    # behind it. Shorter than the venue clients' 10s on purpose: nothing
    # downstream waits on an alert, so there is no reason to be patient.
    alert_send_timeout_seconds: float = Field(default=5.0)

    # At most one alert per (logger, message template) per this window.
    #
    # 15 minutes is chosen against the retry chain above, not picked round: a
    # failing job waits 30 + 60 + 120 + 240 = 450s across its five attempts
    # and logs the same ERROR each time, so a window shorter than that sends
    # five alerts for one incident. The suppressed ones are counted and the
    # next alert for that key names the total, so nothing is lost — a channel
    # that floods is a channel whose owner learns to swipe it away, which is
    # the original defect with an extra step.
    alert_throttle_window_seconds: float = Field(default=900.0)

    # How long a finished (DONE) job row is kept before jobs.purge deletes it.
    #
    # The window is a debugging one, not a correctness one: nothing reads a
    # DONE row back. Idempotency lives on ``signals`` (ux_signals_idempotency),
    # and the recurring seeder deliberately ignores DONE. Seven days is long
    # enough that a Monday investigation still covers the weekend the incident
    # happened on.
    #
    # FAILED rows are NOT subject to this and are never deleted — a chain that
    # exhausted its retries leaves no other trace.
    job_retention_days: int = Field(default=7)

    # How long a failed job waits before the worker may claim it again, and the
    # ceiling that wait grows to: delay = min(base * 2 ** (attempts - 1), cap).
    #
    # These are the two numbers that decide how long a transient fault has to
    # last before it kills a self-scheduling chain, and the reason they exist is
    # that the answer used to be 27 seconds. On 2026-09-18 Bybit's clock ran
    # 5,112ms ahead of this host against a 5,000ms recv_window; ``fail()`` put
    # the job straight back to PENDING without touching ``run_after``, the
    # worker reclaimed it on the next poll, and five attempts were spent inside
    # half a minute. balance.sync went FAILED and stayed dead for 19 hours while
    # the clock that caused it had already corrected itself.
    #
    # With ``max_attempts=5`` there are four waits between the five attempts:
    # 30 + 60 + 120 + 240 = 450s, so a fault has to outlive roughly 7.5 minutes
    # of waiting — about 15.5 minutes of wall clock once the attempts
    # themselves are counted — before the chain dies. That is the whole point:
    # long enough to cover a clock step, an NTP correction or a venue's
    # maintenance window, short enough that a genuinely broken chain still ends
    # rather than retrying forever.
    #
    # The cap only binds a job with more attempts than the default five (the
    # fifth wait would be 480s, the sixth 960s), so raising ``max_attempts``
    # lengthens the chain's life without letting a single retry drift hours out.
    job_retry_backoff_base_seconds: float = Field(default=30.0)
    job_retry_backoff_max_seconds: float = Field(default=600.0)

    # How often the worker re-seeds the recurring chains while it runs.
    #
    # Seeding used to happen once, at startup. ``RecurringJobSeeder`` is the
    # only thing that revives a chain that exhausted its retries, so "restart
    # the worker" was the entire recovery procedure — and nothing restarts the
    # worker. That is the 19 hours.
    #
    # Five minutes, not the 2s claim-loop cadence: a re-seed takes an advisory
    # lock and scans ``jobs`` for a live row per chain, and a dead chain is an
    # hours-scale event, so a finer cadence buys nothing and pays for it on
    # every tick. Five minutes bounds the blind window at five minutes instead
    # of "until a human looks".
    recurring_seed_interval_seconds: float = Field(default=300.0)

    # How often jobs.purge deletes DONE rows past the retention window.
    #
    # Once a day, because retention is measured in days: a finer cadence only
    # scans the table more often to find the same rows, and the purge is the
    # one recurring job whose work does not exist until a day's worth of
    # history has accumulated.
    jobs_purge_interval_seconds: float = Field(default=86_400.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
