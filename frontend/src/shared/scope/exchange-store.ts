import { matchPath } from "react-router";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { usePools } from "@/shared/api/pools";
import { createSafeStorage } from "@/shared/auth/safe-storage";

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

/** The distinct exchanges of a pool list, in first-seen order. */
export function distinctExchanges(pools: readonly { exchange: string }[]): string[] {
  return [...new Set(pools.map((pool) => pool.exchange))];
}

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

/** Overview and Strategies (list and detail) are scoped; Settings and the rest are not. */
const SCOPED_PATHS = ["/", "/strategies", "/strategies/:strategyId"];

export function isExchangeScoped(pathname: string): boolean {
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

export function useExchangeScope(): ExchangeScope {
  const pools = usePools();
  const selected = useExchangeStore((state) => state.selected);
  const select = useExchangeStore((state) => state.select);

  if (pools.status === "pending") return { status: "loading" };
  if (pools.status === "error") return { status: "error" };

  const options = distinctExchanges(pools.data);
  return { status: "ready", options, exchange: resolveExchange(options, selected), select };
}
