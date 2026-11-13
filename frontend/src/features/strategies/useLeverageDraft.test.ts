import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useLeverageDraft } from "@/features/strategies/useLeverageDraft";

describe("useLeverageDraft, under the cap of a stop level", () => {
  it("never takes a step above the cap: the text and the handle stop at it", () => {
    const { result } = renderHook(() => useLeverageDraft(3, undefined, 9));

    act(() => result.current.changeStep(15));

    expect(result.current.text).toBe("9");
    expect(result.current.handle).toBe(9);
    expect(result.current.reading).toEqual({ valid: true, value: 9 });
  });

  it("takes a step at or below the cap as it is", () => {
    const { result } = renderHook(() => useLeverageDraft(3, undefined, 9));

    act(() => result.current.changeStep(6));

    expect(result.current.text).toBe("6");
    expect(result.current.handle).toBe(6);
  });

  it("reads a typed value above the cap as out of range", () => {
    const { result } = renderHook(() => useLeverageDraft(3, undefined, 9));

    act(() => result.current.changeText("10"));

    expect(result.current.reading).toEqual({ valid: false, refusal: "out-of-range" });
  });
});
