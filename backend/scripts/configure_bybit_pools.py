"""Leaves exactly one capital pool enabled, for the venue that is registered.

This is NOT a test and NOT a migration. Pool rows are configuration, not
schema: which pools exist is an operator's decision, and a migration would
impose it on every deployment.

**Why one.** Bybit's Unified Trading Account does not segregate collateral --
one USDT balance stands behind spot and linear perpetuals together. Two pools
over that balance would each read the same pot, so the allocation engine could
reserve the same money twice, with every reservation looking perfectly valid
on its own. ``BybitBalanceReader`` refuses that configuration outright, which
means the balance sync fails until this is fixed.

The pools left over from the Pionex era are DISABLED, not deleted. ``strategies``
carries a composite foreign key into ``capital_pools``, so deleting a row would
either fail or orphan a strategy -- and a disabled pool is recoverable, which a
deleted one is not.

Idempotent: running it again changes nothing.

Usage:
    cd backend
    uv run python scripts/configure_bybit_pools.py            # preview
    uv run python scripts/configure_bybit_pools.py --confirm
"""

import argparse
import asyncio
import sys
from decimal import Decimal

from sqlalchemy import text

from strategy_manager.shared.db import engine, session_factory

# The one pool the registered adapter serves. BybitFuturesExchangeAdapter
# declares usdt-m and nothing else: Bybit also settles linear perpetuals in
# USDC, but USDC is not in the Currency enum or the capital_pools CHECK.
KEEP_VENUE = "usdt-m"
KEEP_CURRENCY = "USDT"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-order-size",
        type=Decimal,
        default=None,
        help=(
            "set the kept pool's minimum. It is ONE number doing TWO jobs: a "
            "signal whose requested amount falls below it is skipped, and so "
            "is a partial fill that would land below it."
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

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT venue, settlement_currency, enabled, min_order_size "
                    "FROM capital_pools ORDER BY venue, settlement_currency"
                )
            )
        ).all()

        print("capital_pools now:")
        for venue, currency, enabled, minimum in rows:
            keep = venue == KEEP_VENUE and currency == KEEP_CURRENCY
            mark = "KEEP   " if keep else "disable"
            print(f"  {mark} {venue}/{currency}  enabled={enabled} min={minimum}")

        strategies = (
            await session.execute(
                text(
                    "SELECT count(*) FROM strategies WHERE NOT "
                    "(venue = :venue AND settlement_currency = :currency)"
                ),
                {"venue": KEEP_VENUE, "currency": KEEP_CURRENCY},
            )
        ).scalar()

        if strategies:
            # A strategy on a pool about to be disabled would accept every
            # signal and size none of them. Better to say so than to let it
            # fail one signal at a time.
            print(
                f"\nWARNING: {strategies} strategy/strategies point at a pool "
                "this would disable. They would stop being sizable.",
                file=sys.stderr,
            )

        if not args.confirm:
            print("\nPREVIEW ONLY. Nothing was changed.")
            return 0

        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = (venue = :venue AND "
                "settlement_currency = :currency)"
            ),
            {"venue": KEEP_VENUE, "currency": KEEP_CURRENCY},
        )
        if args.min_order_size is not None:
            await session.execute(
                text(
                    "UPDATE capital_pools SET min_order_size = :minimum "
                    "WHERE venue = :venue AND settlement_currency = :currency"
                ),
                {
                    "minimum": args.min_order_size,
                    "venue": KEEP_VENUE,
                    "currency": KEEP_CURRENCY,
                },
            )
        await session.commit()

        after = (
            await session.execute(
                text(
                    "SELECT venue, settlement_currency, min_order_size "
                    "FROM capital_pools WHERE enabled ORDER BY venue"
                )
            )
        ).all()
        print("enabled now:")
        for venue, currency, minimum in after:
            print(f"  {venue}/{currency}  min_order_size={minimum}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
