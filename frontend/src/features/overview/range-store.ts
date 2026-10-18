import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { DEFAULT_RANGE, RANGES } from "@/features/overview/RangeSelector";
import type { RangeName } from "@/features/overview/RangeSelector";
import { createSafeStorage } from "@/shared/auth/safe-storage";

/**
 * The chart range the operator last picked, one for the whole panel (every pool
 * on the Overview and every strategy page), persisted through `safe-storage` so
 * a reload keeps it and a blocked `localStorage` never breaks the page.
 */
export const RANGE_STORAGE_KEY = "sm.range";

interface RangeState {
  range: RangeName;
  setRange: (range: RangeName) => void;
}

function isRangeName(value: unknown): value is RangeName {
  return RANGES.some((range) => range === value);
}

export const useRangeStore = create<RangeState>()(
  persist(
    (set) => ({
      range: DEFAULT_RANGE,
      setRange: (range) => set({ range }),
    }),
    {
      name: RANGE_STORAGE_KEY,
      storage: createJSONStorage(() => createSafeStorage()),
      partialize: (state) => ({ range: state.range }),
      // Storage is untrusted: a stale or wrong-typed value must never reach the
      // selector or `report.ranges.find`, so anything else reads as the default.
      merge: (persisted, current) => {
        const stored = (persisted as { range?: unknown } | null | undefined)?.range;
        return { ...current, range: isRangeName(stored) ? stored : DEFAULT_RANGE };
      },
    },
  ),
);
