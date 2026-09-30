import { parseDecimal } from "@/features/overview/format";
import type { Pool } from "@/shared/api/types";

/** Settlement currencies that are worth one US dollar each, so their balances are comparable. */
const USD_STABLECOINS: ReadonlySet<string> = new Set(["USDT"]);

function availableOf(pool: Pool): number {
  const value = pool.balance === null ? null : parseDecimal(pool.balance.available);
  return value ?? Number.NEGATIVE_INFINITY;
}

function rank(pool: Pool): number {
  if (!pool.enabled) return 3 + (USD_STABLECOINS.has(pool.settlement_currency) ? 0 : 1);
  return USD_STABLECOINS.has(pool.settlement_currency) ? 0 : 1;
}

/**
 * The INTERIM order of an exchange's pools on the Overview, deterministic and
 * never a sum: enabled pools first; then the pools settled in a USD stablecoin,
 * the larger available balance first; then every other currency by code.
 * The wanted order is descending USD value, which needs a server-side valuation
 * per pool (task 11f.1); until then only stablecoins can be ranked against one
 * another, because nothing here knows what a BTC or an ETH is worth.
 *
 * Disabled pools keep the same inner order, after the enabled ones. The input is
 * not modified, and pools that tie keep the server's order.
 */
export function orderPools(pools: readonly Pool[]): Pool[] {
  return [...pools].sort((a, b) => {
    const byGroup = rank(a) - rank(b);
    if (byGroup !== 0) return byGroup;
    if (USD_STABLECOINS.has(a.settlement_currency)) {
      const left = availableOf(a);
      const right = availableOf(b);
      if (left === right) return 0;
      return left > right ? -1 : 1;
    }
    if (a.settlement_currency === b.settlement_currency) return 0;
    return a.settlement_currency < b.settlement_currency ? -1 : 1;
  });
}
