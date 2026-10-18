import { beforeEach, describe, expect, it, vi } from "vitest";

import { RANGE_STORAGE_KEY, useRangeStore } from "@/features/overview/range-store";

describe("range store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useRangeStore.setState({ range: "30D" });
  });

  it("starts at the default range, 30D", () => {
    expect(useRangeStore.getState().range).toBe("30D");
  });

  it("persists the chosen range under the sm.range key", () => {
    useRangeStore.getState().setRange("1Y");

    const raw = window.localStorage.getItem("sm.range");
    expect(RANGE_STORAGE_KEY).toBe("sm.range");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).state.range).toBe("1Y");
  });

  it("reads a stored range back after a reload", async () => {
    window.localStorage.setItem("sm.range", JSON.stringify({ state: { range: "90D" }, version: 0 }));

    await useRangeStore.persist.rehydrate();

    expect(useRangeStore.getState().range).toBe("90D");
  });

  it.each([
    ["an unknown name", { range: "2W" }],
    ["a wrong type", { range: 7 }],
    ["a missing field", {}],
    ["a null", { range: null }],
  ])("reads %s from storage as the default range", async (_label, state) => {
    useRangeStore.setState({ range: "7D" });
    window.localStorage.setItem("sm.range", JSON.stringify({ state, version: 0 }));

    await useRangeStore.persist.rehydrate();

    expect(useRangeStore.getState().range).toBe("30D");
  });

  it("degrades to memory when localStorage throws (private mode)", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => useRangeStore.getState().setRange("All")).not.toThrow();
    expect(useRangeStore.getState().range).toBe("All");

    setItemSpy.mockRestore();
  });
});
