"""What ``store_binance_credentials.py`` and ``store_bybit_credentials.py`` share.

Both scripts do the same three things and differ only in the confirmations the
owner gives: read a TRADE credential from a terminal, hand it to
``SaveCredential``, and say what happened. Keeping that here means the two
scripts cannot drift apart, and the API (PR 8a-3) reaches the same use case, so
every path records the same facts.

**Nothing here ever prints a key or a secret.** The last four characters of the
key are the most that reaches a terminal. Every refusal detail comes from the
use case and names tokens or fields, never a payload.

The prompt and the saver are injected into ``run_store``, so the scripts are
tested end to end with fakes (rule 1: no test needs a real credential, a
database or a venue).
"""

import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from getpass import getpass

from strategy_manager.accounts.application.save_credential import (
    SaveCredential,
    Saved,
    SaveOutcome,
    SaveRefused,
    SaveResult,
)
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, FactSource
from strategy_manager.accounts.domain.key_policy import READ_ONLY_WARNING, OwnerConfirmations
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.key_inspectors.registry import (
    KeyInspectorRegistry,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher

LABEL = "default"

SaveFn = Callable[[ExchangeCredential, OwnerConfirmations], Awaitable[SaveResult]]
PromptFn = Callable[[], ExchangeCredential | None]
SaverFactory = Callable[[], SaveFn | None]

_WHAT_TO_DO = {
    SaveOutcome.KEY_REJECTED: (
        "Fix the key, or the IP it is bound to, in the venue and run this again."
    ),
    SaveOutcome.VENUE_UNREACHABLE: (
        "The venue could not be asked, so nothing is known about this key. "
        "Run this again in a moment."
    ),
    SaveOutcome.WITHDRAW_PERMISSION: (
        "This system never withdraws, so the permission has no upside to trade "
        "against. Remove it in the venue and run this again."
    ),
    SaveOutcome.PERMISSIONS_UNAVAILABLE: (
        "The venue did not report the key's permissions in a shape that can be "
        "trusted, so the key is refused rather than guessed at."
    ),
    SaveOutcome.CONCURRENT_SAVE: (
        "Another save for this exchange was stored first. Check which key is "
        "active before running this again."
    ),
}


class RoundTripFailed(Exception):
    """The credential was committed but did not decrypt back to what was given."""


def explain_needs_a_terminal(script: str) -> None:
    print(
        "\n\nThis script prompts for the credential rather than reading it from\n"
        "a file, so it needs a real terminal. Nothing was stored.\n\n"
        "Run it yourself:\n"
        "    cd backend\n"
        f"    uv run python scripts/{script}",
        file=sys.stderr,
    )


def prompt_credential(exchange: str, venue: str, script: str) -> ExchangeCredential | None:
    """Reads the credential from a terminal, or explains why it cannot.

    ``sys.stdin.isatty()`` is checked but not trusted: some runners report a
    TTY and then hand the prompt an immediate EOF. Catching ``EOFError`` is what
    actually distinguishes "a person is typing" from "something is piping", and
    the difference matters: the alternative is a traceback where an instruction
    belongs.
    """
    if not sys.stdin.isatty():
        explain_needs_a_terminal(script)
        return None

    # Neither half is echoed. The key used to be read with input(), and on
    # 2026-09-30 a full Binance key was printed on the owner's terminal and
    # copied from there into a chat. A key is a credential too.
    print(f"Paste the {venue} TRADE credential. Neither the key nor the secret is echoed.\n")
    try:
        api_key = getpass("API key:    ").strip()
        api_secret = getpass("API secret: ").strip()
    except (EOFError, KeyboardInterrupt):
        explain_needs_a_terminal(script)
        return None

    try:
        return ExchangeCredential(
            exchange=exchange, label=LABEL, api_key=api_key, api_secret=api_secret
        )
    except InvariantViolation as exc:
        print(f"\n{exc}", file=sys.stderr)
        return None


def vault_saver() -> SaveFn | None:
    """The real wiring: the vault, the venue inspectors, the system clock.

    Returns ``None`` after explaining when the master key is unusable, so the
    script stops BEFORE the owner types a secret for a run that cannot succeed.
    """
    settings = get_settings()
    try:
        cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    except InvariantViolation as exc:
        print(f"MASTER_ENCRYPTION_KEY problem: {exc}", file=sys.stderr)
        return None

    # A signed Binance URL carries its signature in the query, and httpx logs
    # URLs at INFO. Nothing here configures logging, but a script must not rely
    # on that staying true.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    clock = SystemClock()
    inspectors = KeyInspectorRegistry.for_settings(settings, clock)

    async def save(credential: ExchangeCredential, confirmations: OwnerConfirmations) -> SaveResult:
        try:
            async with session_factory() as session:
                vault = SqlAlchemyCredentialVault(session, cipher, clock)
                result = await SaveCredential(
                    inspectors, vault, SqlAlchemyCapitalPoolWriter(session), session, clock
                ).execute(credential, confirmations)
                if isinstance(result, Saved):
                    # Prove the round trip before reporting success: a credential
                    # that seals but cannot be opened is worse than none at all.
                    reopened = await vault.load(credential.exchange)
                    if reopened.api_key != credential.api_key:
                        raise RoundTripFailed(
                            "stored credential did not survive a decrypt round trip"
                        )
                return result
        finally:
            await engine.dispose()

    return save


async def run_store(
    *,
    confirmations: OwnerConfirmations,
    prompt: PromptFn,
    make_saver: SaverFactory,
) -> int:
    """The part of a store script after its own arguments are settled."""
    saver = make_saver()
    if saver is None:
        return 1

    credential = prompt()
    if credential is None:
        return 1

    try:
        result = await saver(credential, confirmations)
    except RoundTripFailed as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    return report(result, credential)


def report(result: SaveResult, credential: ExchangeCredential) -> int:
    if isinstance(result, SaveRefused):
        return _report_refusal(result, credential.exchange)
    return _report_saved(result, credential)


def _report_refusal(result: SaveRefused, exchange: str) -> int:
    print(f"\nREFUSED ({result.outcome.value}): {result.detail}", file=sys.stderr)
    guidance = _WHAT_TO_DO.get(result.outcome)
    if guidance:
        print(f"  {guidance}", file=sys.stderr)
    print(f"  Nothing was stored for {exchange}.", file=sys.stderr)
    return 1


def _report_saved(result: Saved, credential: ExchangeCredential) -> int:
    facts = result.facts
    print(f"\nsealed {credential.exchange}/{credential.label} (key ending {result.last4})")
    trade = _describe(facts.trade_capability_source, facts.trade_confirmed_at)
    withdraw = _describe(facts.withdraw_check, facts.withdraw_confirmed_at)
    print(f"  trade capability   {trade}")
    print(f"  withdraw check     {withdraw}")
    if facts.internal_transfer is not None:
        print(f"  internal transfer  {'yes' if facts.internal_transfer else 'no'}")
    print(f"  validated at       {_moment(facts.validated_at)}")

    if FactSource.OWNER_CONFIRMED in (facts.trade_capability_source, facts.withdraw_check):
        print(
            "\nNOTE: this venue cannot be asked, so the record says you confirmed these\n"
            "  two settings, not that they were checked. A wrong confirmation shows up\n"
            "  as a rejected first live order and a Telegram alert."
        )
    if READ_ONLY_WARNING in result.warnings:
        print(
            f"\nWARNING {READ_ONLY_WARNING}: this key cannot trade. It is stored anyway\n"
            "  (one active key per exchange, read-only accepted), and it replaces the\n"
            "  previous active key. Orders on this exchange will fail until a trading\n"
            "  key is stored."
        )

    print("\nthe worker reads this credential from the database, never the environment")
    return 0


def _describe(source: FactSource, confirmed_at: datetime | None) -> str:
    if source is FactSource.OWNER_CONFIRMED:
        return f"OWNER_CONFIRMED (you confirmed on {_moment(confirmed_at)})"
    return source.value


def _moment(moment: datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment is not None else "not recorded"

