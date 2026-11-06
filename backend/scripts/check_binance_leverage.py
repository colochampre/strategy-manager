"""Manual check (H.9): the two facts about Binance's settings H.5 was built without.

This is NOT a test. It needs a real key and talks to the live venue, which is
why it lives here and not under tests/ (CLAUDE.md rule 1).

Since decision 38 the worker SETS a pair's margin type and leverage before
every live opening, and reads both back. Two things that code depends on were
never seen on the wire:

  SPELLING  How ``GET /fapi/v1/symbolConfig`` spells an isolated pair's
            ``marginType``. The docs do not say, so ``_is_isolated`` compares
            ignoring case. Read on a pair that IS isolated, the answer settles
            whether that tolerance is needed.
  REFUSAL   Which code Binance answers when the leverage asked is above the
            pair's maximum, and whether ``_is_definitive_rejection`` reads it
            as a refusal (the opening ends as LEVERAGE_NOT_APPLIED) or as an
            unknown outcome (the job retries).

**It previews by default and only asks for the refused leverage with
``--confirm``.** The preview reads ``symbolConfig``, ``leverageBracket`` and
the pair's position, and sends nothing.

With ``--confirm`` it sends ONE ``POST /fapi/v1/leverage`` asking for the
pair's maximum plus one, which no pair accepts. It refuses to send it unless
the pair is flat, so no position can be touched, and it reads the pair's
settings back afterwards. Should Binance ever accept it, the pair's original
leverage is written back at once and the run fails loudly.

Usage:
    cd backend
    uv run python scripts/check_binance_leverage.py --user-email <e-mail> --symbol SOLUSDT
    uv run python scripts/check_binance_leverage.py --user-email <e-mail> --symbol SOLUSDT --confirm
"""

import argparse
import asyncio
import io
import json
import sys
from decimal import Decimal
from typing import Any

from probe_credentials import add_user_email_argument, announce, vault_credentials

from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    _is_definitive_rejection,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.binance import EXCHANGE as BINANCE_EXCHANGE
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.factory import (
    futures_transport,
    read_only_client,
)
from strategy_manager.shared.infrastructure.binance.signer import BinanceCredentials

SYMBOL_CONFIG_PATH = "/fapi/v1/symbolConfig"
LEVERAGE_BRACKET_PATH = "/fapi/v1/leverageBracket"
LEVERAGE_PATH = "/fapi/v1/leverage"


def bracket_max(payload: object, symbol: str) -> int:
    """The highest ``initialLeverage`` among the pair's brackets.

    ``leverageBracket`` answers a list, one entry per symbol; asked for one
    symbol it may answer that entry alone, so both shapes are read. Anything
    else raises ``ValueError`` naming the pair: a maximum is never guessed,
    because the refused request is sized from it.
    """
    entries = [payload] if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError(f"{LEVERAGE_BRACKET_PATH} for {symbol} is not a list or an object")
    entry = next(
        (e for e in entries if isinstance(e, dict) and e.get("symbol") == symbol), None
    )
    if entry is None:
        raise ValueError(f"{LEVERAGE_BRACKET_PATH} has no entry for {symbol}")
    brackets = entry.get("brackets")
    if not isinstance(brackets, list) or not brackets:
        raise ValueError(f"{LEVERAGE_BRACKET_PATH} lists no brackets for {symbol}")
    leverages = [b.get("initialLeverage") if isinstance(b, dict) else None for b in brackets]
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in leverages):
        raise ValueError(
            f"{LEVERAGE_BRACKET_PATH} has a bracket of {symbol} with no whole initialLeverage"
        )
    return max(x for x in leverages if isinstance(x, int))


def _is_isolated(margin_type: str) -> bool:
    """The adapter's own comparison, copied rather than imported: this probe
    runs before H.5 is deployed, on a checkout that does not have it yet."""
    return margin_type.upper() == "ISOLATED"


def spelling_verdict(margin_type: str) -> str:
    """What one ``marginType`` read says about ``_is_isolated``'s tolerance."""
    if margin_type == "ISOLATED":
        return "ISOLATED, exactly as _is_isolated expects"
    if _is_isolated(margin_type):
        return f"isolated: {margin_type}, in another case than ISOLATED"
    return f"NOT isolated: {margin_type}"


def _dump(value: Any) -> None:
    print("  " + json.dumps(value, indent=2).replace("\n", "\n  "))


def _whole(value: Decimal) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"the pair's leverage {value} is not a whole number")
    return int(value)


async def _run(symbol: str, confirm: bool, settings: Any, credentials: BinanceCredentials) -> int:
    async with (
        futures_transport(settings, credentials) as futures,
        read_only_client(settings, credentials) as reader,
    ):
        print(f"\nSPELLING  GET {SYMBOL_CONFIG_PATH}?symbol={symbol}")
        config = await futures.get_signed(SYMBOL_CONFIG_PATH, {"symbol": symbol})
        _dump(config)
        entry = config[0] if isinstance(config, list) and config else config
        if not isinstance(entry, dict) or not isinstance(entry.get("marginType"), str):
            print("  FAILED: no marginType string in the answer")
            return 1
        margin_type: str = entry["marginType"]
        original = _whole(Decimal(str(entry.get("leverage"))))
        print(f"  marginType -> {spelling_verdict(margin_type)}")
        if not _is_isolated(margin_type):
            print(
                "  This pair is not isolated, so its spelling does not settle the "
                "isolated one. Run again on a pair that is."
            )

        print(f"\nMAXIMUM   GET {LEVERAGE_BRACKET_PATH}?symbol={symbol}")
        maximum = bracket_max(
            await futures.get_signed(LEVERAGE_BRACKET_PATH, {"symbol": symbol}), symbol
        )
        asked = maximum + 1
        print(f"  maximum {maximum}x, so the refused request would ask {asked}x")

        print(f"\nPOSITION  {symbol}")
        position = await reader.position_for(symbol)
        flat = position is None or not position.is_open
        print("  flat" if position is None or flat else f"  OPEN: size {position.signed_size}")

        if not confirm:
            print(f"\nPreview only, nothing was sent. --confirm asks {asked}x once.")
            return 0
        if not flat:
            print("\nREFUSED: the pair holds a position, and this probe never touches one.")
            return 1

        print(f"\nREFUSAL   POST {LEVERAGE_PATH} symbol={symbol} leverage={asked}")
        try:
            accepted = await futures.post(
                LEVERAGE_PATH, {"symbol": symbol, "leverage": str(asked)}
            )
        except BinanceApiError as exc:
            print(f"  refused: code={exc.code!r} http={exc.http_status!r}: {exc}")
            definitive = _is_definitive_rejection(exc)
            print(
                "  _is_definitive_rejection -> "
                + (
                    "True: the opening ends as LEVERAGE_NOT_APPLIED"
                    if definitive
                    else "False: the job would RETRY a refusal that never changes"
                )
            )
        else:
            print(f"  UNEXPECTED: Binance ACCEPTED {asked}x: {accepted}")
            await futures.post(LEVERAGE_PATH, {"symbol": symbol, "leverage": str(original)})
            print(f"  wrote the original {original}x back")
            definitive = False

        print(f"\nREAD BACK GET {SYMBOL_CONFIG_PATH}?symbol={symbol}")
        after = await futures.get_signed(SYMBOL_CONFIG_PATH, {"symbol": symbol})
        _dump(after)
        after_entry = after[0] if isinstance(after, list) and after else after
        unchanged = (
            isinstance(after_entry, dict)
            and after_entry.get("marginType") == margin_type
            and _whole(Decimal(str(after_entry.get("leverage")))) == original
        )
        print(f"  settings unchanged: {'YES' if unchanged else 'NO -- check the pair by hand'}")
        return 0 if definitive and unchanged else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--confirm", action="store_true")
    add_user_email_argument(parser)
    args = parser.parse_args()
    symbol = args.symbol.upper()

    settings = get_settings()
    print(f"Binance futures URL: {settings.binance_futures_base_url}")
    print(f"Pair: {symbol}  mode: {'CONFIRM (one refused write)' if args.confirm else 'preview'}")

    async with vault_credentials(
        settings, BINANCE_EXCHANGE, user_email=args.user_email
    ) as vaulted:
        announce(vaulted, f"vault ({BINANCE_EXCHANGE})")
        credentials = BinanceCredentials(api_key=vaulted.api_key, api_secret=vaulted.api_secret)
        return await _run(symbol, args.confirm, settings, credentials)


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
