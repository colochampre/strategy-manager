import { useQuery } from "@tanstack/react-query";
import { matchPath } from "react-router";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { useCredentials } from "@/shared/api/credentials";
import { fetchOpenPositions, OPEN_POSITIONS_KEY } from "@/shared/api/positions";
import { usePools } from "@/shared/api/pools";
import { useStrategies } from "@/shared/api/strategies";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import { createSafeStorage } from "@/shared/auth/safe-storage";
import { distinctExchanges, runningExchanges } from "@/shared/scope/running-exchanges";

/**
 * The exchange the operator last picked, persisted through `safe-storage` so a
 * reload keeps it and a blocked `localStorage` (private mode) never breaks the
 * page. It is only a PREFERENCE: whether it is usable is decided against the
 * live pool list by `resolveExchange`, never by what storage claims.
 */
export const EXCHANGE_STORAGE_KEY = "sm.exchange";

interface ExchangeState {
  selected: string | null;
  select: (exchange: string) => void;
}

export const useExchangeStore = create<ExchangeState>()(
  persist(
    (set) => ({
      selected: null,
      select: (exchange) => set({ selected: exchange }),
    }),
    {
      name: EXCHANGE_STORAGE_KEY,
      storage: createJSONStorage(() => createSafeStorage()),
      partialize: (state) => ({ selected: state.selected }),
    },
  ),
);

export { distinctExchanges };

/**
 * The exchange to show: the stored choice while it is still an option,
 * otherwise the first option. A stale value (an exchange whose pools are
 * gone) or one of the wrong type, read from storage, therefore falls back
 * instead of scoping every view to an exchange that does not exist.
 */
export function resolveExchange(options: readonly string[], selected: string | null): string | null {
  if (selected !== null && options.includes(selected)) return selected;
  return options[0] ?? null;
}

/**
 * Overview and the authored strategies (list and detail) are scoped; Settings and the rest are not. Neither is
 * what crosses exchanges: My subscriptions, and Explore, whose path `:strategyId` would otherwise match.
 */
const SCOPED_PATHS = ["/", "/strategies/authored", "/strategies/:strategyId"];
const EXPLORE_PATH = "/strategies/explore";

export function isExchangeScoped(pathname: string): boolean {
  if (matchPath({ path: EXPLORE_PATH, end: true }, pathname) !== null) return false;
  return SCOPED_PATHS.some((path) => matchPath({ path, end: true }, pathname) !== null);
}

/**
 * What a scoped view may rely on. `loading` and `error` carry no exchange on
 * purpose: a view that cannot tell which exchange it is showing must not show
 * pool-scoped data at all, because unfiltered data under a tab that claims a
 * filter is the failure this scope exists to prevent (rule 7).
 */
export type ExchangeScope =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; options: string[]; exchange: string | null; select: (exchange: string) => void };

const OPEN_POSITIONS_REFRESH_MS = 60_000;

export function useExchangeScope(): ExchangeScope {
  const pools = usePools();
  const credentials = useCredentials();
  // The same query as `useOpenPositions`, but held back until there is a pool to scope: a page with no
  // exchange asks the server for nothing about positions.
  const positions = useQuery({
    queryKey: OPEN_POSITIONS_KEY,
    queryFn: fetchOpenPositions,
    staleTime: OPEN_POSITIONS_REFRESH_MS,
    refetchInterval: OPEN_POSITIONS_REFRESH_MS,
    enabled: pools.status === "success" && pools.data.length > 0,
  });
  const strategies = useStrategies(false);
  const subscriptions = useHeldSubscriptions();
  const selected = useExchangeStore((state) => state.selected);
  const select = useExchangeStore((state) => state.select);

  if (pools.status === "pending") return { status: "loading" };
  if (pools.status === "error") return { status: "error" };

  // Only a source that succeeded has answered; a loading or failed one keeps every pool exchange.
  const options = runningExchanges({
    pools: pools.data,
    credentials: credentials.status === "success" ? credentials.data : undefined,
    positions: positions.status === "success" ? positions.data : undefined,
    strategies: strategies.status === "success" ? strategies.data : undefined,
    subscriptions: subscriptions.status === "success" ? subscriptions.data : undefined,
  });
  return { status: "ready", options, exchange: resolveExchange(options, selected), select };
}
