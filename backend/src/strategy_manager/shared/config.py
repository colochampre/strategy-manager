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

    # Master key for envelope-encrypting exchange API credentials at rest.
    # 32 bytes, base64-encoded.
    master_encryption_key: str = Field(default="")

    cors_origins: list[str] = Field(default=["http://localhost:5173"])

    # How long a PENDING/SUBMITTED reservation stays inside "active" pool
    # availability before it is excluded and eligible for sweeping.
    reservation_ttl_seconds: int = Field(default=30)

    # How long the worker sleeps between polls when it finds no claimable job.
    worker_poll_interval_seconds: float = Field(default=2.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
