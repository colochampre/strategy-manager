"""Seals a Binance trade credential into the vault, through ``SaveCredential``.

**It prompts. It does not read the environment, and that is the point.**

The vault holds ONE active key per exchange, and that key signs every read and
every order (decision 18). Nothing reads a Binance key from ``.env`` any more.
So the key given here must be the TRADING key: sealing the old ``.env``
read-only key would supersede the trading key and leave Binance able to read
and unable to trade. That confusion has already cost this project one wrong
conclusion, on Pionex, where a write refused for using the read-only key looked
identical to a write the venue forbade.

So a trading key goes from your clipboard to the vault without ever being
written to a file. The secret is read with ``getpass`` and never echoed.

**Two things Binance cannot be asked, so you say them.** Nothing reachable
reveals whether a key can withdraw (SAPI ``apiRestrictions`` answers 403 from
the VPS, and ``canWithdraw`` is an account-level flag), or whether it has
"Enable Futures" (a key without it still reads every fapi endpoint). Decisions
24 and 30 make both of them YOUR statement, made on the command line:

    --confirm-withdrawals-disabled   you checked in Binance: withdrawals are OFF
    --confirm-futures-enabled        you checked in Binance: Enable Futures is ON

Without both the script prints which is missing to stderr, exits 2, and stores
nothing. That check runs before the secret prompt, so no secret is typed for a
run that cannot succeed. There is no environment variable, no ``--yes`` and no
default: the flags are the statement.

The record keeps who vouched for each fact. It stores OWNER_CONFIRMED with the
moment you confirmed, and never claims Binance verified either one. A wrong
confirmation is caught by the venue: the first live order is rejected, and the
alert reaches Telegram.

What it does check is the live read (``GET /fapi/v3/account``, signed): the key
authenticates from this host. It then goes through ``SaveCredential``, exactly
as the API does, so both paths record the same facts.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path. A rotation inherits no
confirmation: the new key is confirmed on its own.

Usage -- run it yourself, in your own terminal, since it prompts:
    cd backend
    uv run python scripts/store_binance_credentials.py
        --confirm-withdrawals-disabled --confirm-futures-enabled
    (one line; wrapped here)
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from credential_cli import (
    PromptFn,
    RoundTripFailed,
    SaverFactory,
    prompt_credential,
    run_store,
    vault_saver,
)

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations
from strategy_manager.shared.infrastructure.binance import EXCHANGE

SCRIPT = "store_binance_credentials.py"

WITHDRAWALS_FLAG = "--confirm-withdrawals-disabled"
FUTURES_FLAG = "--confirm-futures-enabled"

__all__ = ["RoundTripFailed", "build_parser", "confirmations_from", "main"]


def build_parser() -> argparse.ArgumentParser:
    """No flag defaults to confirmed, and abbreviations are off: ``--confirm``
    must not be read as either statement."""
    parser = argparse.ArgumentParser(
        prog=SCRIPT,
        description="Store the Binance trade credential after your two confirmations.",
        allow_abbrev=False,
    )
    parser.add_argument(
        WITHDRAWALS_FLAG,
        action="store_true",
        default=False,
        help="you checked in Binance that this key has withdrawals disabled",
    )
    parser.add_argument(
        FUTURES_FLAG,
        action="store_true",
        default=False,
        help='you checked in Binance that this key has "Enable Futures"',
    )
    return parser


def confirmations_from(parsed: argparse.Namespace) -> OwnerConfirmations:
    return OwnerConfirmations(
        withdrawals_disabled=parsed.confirm_withdrawals_disabled,
        futures_enabled=parsed.confirm_futures_enabled,
    )


def _missing_flags(parsed: argparse.Namespace) -> list[str]:
    return [
        flag
        for flag, given in (
            (WITHDRAWALS_FLAG, parsed.confirm_withdrawals_disabled),
            (FUTURES_FLAG, parsed.confirm_futures_enabled),
        )
        if not given
    ]


def _prompt() -> ExchangeCredential | None:
    return prompt_credential(EXCHANGE, "Binance", SCRIPT)


async def main(
    argv: Sequence[str] | None = None,
    *,
    prompt: PromptFn = _prompt,
    make_saver: SaverFactory = vault_saver,
) -> int:
    try:
        parsed = build_parser().parse_args(argv)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 2

    missing = _missing_flags(parsed)
    if missing:
        print(
            f"Missing confirmation: {', '.join(missing)}\n"
            "  Binance cannot be asked whether this key withdraws or trades futures,\n"
            "  so you state both, after checking them in Binance. Nothing was asked\n"
            "  and nothing was stored. Run this again with the missing flag added.",
            file=sys.stderr,
        )
        return 2

    return await run_store(
        confirmations=confirmations_from(parsed), prompt=prompt, make_saver=make_saver
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
