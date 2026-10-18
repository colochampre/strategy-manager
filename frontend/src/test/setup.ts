import "@testing-library/jest-dom/vitest";

import { beforeEach } from "vitest";

import { RANGE_STORAGE_KEY, useRangeStore } from "@/features/overview/range-store";
import { DEFAULT_RANGE } from "@/features/overview/RangeSelector";
import "@/shared/i18n";

// The chart range is remembered across views and reloads, so without this a
// range chosen in one test would be the starting range of the next.
beforeEach(() => {
  try {
    window.localStorage.removeItem(RANGE_STORAGE_KEY);
  } catch {
    // A test that blocks storage on purpose must not break the reset.
  }
  useRangeStore.setState({ range: DEFAULT_RANGE });
});
