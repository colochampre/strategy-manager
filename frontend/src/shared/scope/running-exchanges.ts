import type { CredentialEntry } from "@/shared/api/credentials";
import type { OpenState } from "@/shared/api/positions";
import type { HeldSubscription, Strategy } from "@/shared/api/types";

/**
 * What each source said. `undefined` means the source has not answered (loading or failed): the rule then
 * keeps every pool exchange it may show, because an unanswered source cannot say that nothing runs.
 */
export interface RunningSources {
  pools: readonly { exchange: string }[];
  credentials: readonly CredentialEntry[] | undefined;
  positions: OpenState | undefined;
  strategies: readonly Strategy[] | undefined;
  subscriptions: readonly HeldSubscription[] | undefined;
}

/** The distinct exchanges of a pool list, in first-seen order. */
export function distinctExchanges(pools: readonly { exchange: string }[]): string[] {
  return [...new Set(pools.map((pool) => pool.exchange))];
}

/**
 * Exchanges that never get a tab, whatever runs there (decision 37, amended 2026-11-06): Pionex offers no
 * futures trading over its public API, so it stays out until that is confirmed to work.
 */
const NEVER_A_TAB: ReadonlySet<string> = new Set(["pionex"]);

/**
 * The exchanges that get a tab (owner decision 37): those where the user has something running, in the
 * order the pools list them. Something running is an active key, an open position, an enabled strategy that
 * is not archived, or an ACTIVE subscription. Pools alone are not enough, and a key is not the only reason,
 * because a new user simulating has no key.
 *
 * While any source has not answered, the pool-derived list stays, so no tab disappears on a guess. Once all
 * have answered and nothing runs anywhere, there is no tab at all (the amendment). Pionex is never listed.
 */
export function runningExchanges(sources: RunningSources): string[] {
  const fromPools = distinctExchanges(sources.pools).filter((exchange) => !NEVER_A_TAB.has(exchange));
  const { credentials, positions, strategies, subscriptions } = sources;
  if (credentials === undefined || positions === undefined || strategies === undefined || subscriptions === undefined) {
    return fromPools;
  }

  const running = new Set<string>();
  for (const key of credentials) {
    if (key.status === "STORED") running.add(key.exchange);
  }
  for (const position of positions.positions) running.add(position.pool.exchange);
  for (const strategy of strategies) {
    if (strategy.enabled && strategy.archived_at === null) running.add(strategy.exchange);
  }
  for (const held of subscriptions) {
    if (held.status === "ACTIVE") running.add(held.exchange);
  }

  return fromPools.filter((exchange) => running.has(exchange));
}
