"""Seals a Bybit trade credential into the vault, through ``SaveCredential``.

**It prompts. It does not read the environment, and that is the point.**

``store_pionex_credentials.py`` takes its credential from ``PIONEX_API_KEY`` /
``PIONEX_API_SECRET``. This one does not: the vault holds ONE active key per
exchange, and that key signs every read and every order (decision 18). Nothing
reads a Bybit key from ``.env`` any more, so the key given here must be the
TRADING key -- sealing the old ``.env`` read-only key would supersede it and
leave Bybit able to read and unable to trade. That confusion has already cost
this project one wrong conclusion, on the other venue, where a write refused
for using the read-only key looked identical to a write the venue forbade.

So a trading key goes from your clipboard to the vault without ever being
written to a file. The secret is read with ``getpass`` and never echoed.

**Bybit is asked, so there is nothing to confirm and no flag to pass.** The
script goes through ``SaveCredential``, exactly as the API does:

- ``GET /v5/account/wallet-balance`` proves the key authenticates from this
  host (an unmatched source IP is reported as a rejected key);
- ``GET /v5/user/query-api`` supplies ``permissions.Wallet``, which must be a
  subset of the transfer allowlist -- a key that can withdraw is refused -- and
  ``readOnly``, which is the only thing that says whether the key can trade.

Anything the venue does not report in a shape that can be trusted is refused,
never guessed at.

**A read-only key is stored, with a warning** (decision 18: one active key per
exchange, read-only accepted). It replaces the previous active key, so use it
knowingly: orders on this exchange fail until a trading key is stored.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path.

Usage -- run it yourself, in your own terminal, since it prompts:
    cd backend
    uv run python scripts/store_bybit_credentials.py
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
from strategy_manager.shared.infrastructure.bybit import EXCHANGE

SCRIPT = "store_bybit_credentials.py"

__all__ = ["RoundTripFailed", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """No flags at all: Bybit is verified server-side, and a confirmation the
    server would drop is refused by the use case anyway."""
    return argparse.ArgumentParser(
        prog=SCRIPT,
        description="Store the Bybit trade credential. Bybit is checked by the venue.",
        allow_abbrev=False,
    )


def _prompt() -> ExchangeCredential | None:
    return prompt_credential(EXCHANGE, "Bybit", SCRIPT)


async def main(
    argv: Sequence[str] | None = None,
    *,
    prompt: PromptFn = _prompt,
    make_saver: SaverFactory = vault_saver,
) -> int:
    try:
        build_parser().parse_args(argv)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 2

    return await run_store(
        confirmations=OwnerConfirmations(), prompt=prompt, make_saver=make_saver
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
