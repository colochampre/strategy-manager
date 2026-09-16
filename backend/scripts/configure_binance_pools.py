"""Enables the Binance USDⓈ-M USDT pool, leaving the other pools alone.

This is NOT a test and NOT a migration. Pool rows are configuration, not
schema: which pools exist is an operator's decision, and a migration would
impose it on every deployment.

**Why only usdt-m.** Binance segregates wallets -- spot, USDⓈ-M futures,
COIN-M futures, margin, funding and earn are separate balances (verified live
2026-09-15). ``BinanceBalanceReader`` speaks to the futures wallet and refuses
any other venue outright, so a ``binance/spot`` pool would fail the balance
sync rather than quietly read the wrong pot.

Unlike its Bybit twin this DISABLES NOTHING. Since migration 0018 a pool is
identified by ``(exchange, venue, settlement_currency)``, so Bybit's
``usdt-m/USDT`` and Binance's are different rows holding different money and
both may be enabled at once -- which is the whole point of running strategies
on either exchange.

Idempotent: running it again changes nothing.

Usage:
    cd backend
    uv run python scripts/configure_binance_pools.py            # preview
    uv run python scripts/configure_binance_pools.py --confirm
"""

import argparse
import asyncio
import sys
from decimal import Decimal

from sqlalchemy import text

from strategy_manager.shared.db import engine, session_factory

EXCHANGE = "binance"
VENUE = "usdt-m"
CURRENCY = "USDT"

# The venue's own floor is 5 USDT of notional (MIN_NOTIONAL, verified
# 2026-09-15 on SFP, AAVE and STX). This is the pool's floor, which is a
# different number: the smallest grant that can still be CLOSED after fees
# and step rounding. Left conservative rather than pinned to the venue's.
DEFAULT_MIN_ORDER_SIZE = Decimal("10")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-order-size",
        type=Decimal,
        default=None,
        help=(
            "the pool's minimum. It is ONE number doing TWO jobs: a signal "
            "whose requested amount falls below it is skipped, and so is a "
            f"partial fill that would land below it. Default {DEFAULT_MIN_ORDER_SIZE}."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="apply the change. Without it this only previews.",
    )
    args = parser.parse_args()

    if args.min_order_size is not None and args.min_order_size <= 0:
        print("--min-order-size must be positive", file=sys.stderr)
        return 1

    minimum = args.min_order_size or DEFAULT_MIN_ORDER_SIZE

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT exchange, venue, settlement_currency, enabled, min_order_size "
                    "FROM capital_pools ORDER BY exchange, venue, settlement_currency"
                )
            )
        ).all()

        print("capital_pools now:")
        existing = False
        for exchange, venue, currency, enabled, current_min in rows:
            target = (exchange, venue, currency) == (EXCHANGE, VENUE, CURRENCY)
            existing = existing or target
            mark = "TARGET " if target else "       "
            print(f"  {mark} {exchange}/{venue}/{currency}  enabled={enabled} min={current_min}")

        print(
            f"\nwould {'enable' if existing else 'INSERT'} {EXCHANGE}/{VENUE}/{CURRENCY} "
            f"with min_order_size={minimum}; every other pool is left untouched."
        )

        if not args.confirm:
            print("\nPREVIEW ONLY. Nothing was changed.")
            return 0

        await session.execute(
            text(
                "INSERT INTO capital_pools "
                "(exchange, venue, settlement_currency, enabled, min_order_size) "
                "VALUES (:exchange, :venue, :currency, true, :minimum) "
                "ON CONFLICT (exchange, venue, settlement_currency) DO UPDATE "
                "SET enabled = true, min_order_size = EXCLUDED.min_order_size"
            ),
            {
                "exchange": EXCHANGE,
                "venue": VENUE,
                "currency": CURRENCY,
                "minimum": minimum,
            },
        )
        await session.commit()

        after = (
            await session.execute(
                text(
                    "SELECT exchange, venue, settlement_currency, min_order_size "
                    "FROM capital_pools WHERE enabled ORDER BY exchange, venue"
                )
            )
        ).all()
        print("enabled now:")
        for exchange, venue, currency, current_min in after:
            print(f"  {exchange}/{venue}/{currency}  min_order_size={current_min}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
