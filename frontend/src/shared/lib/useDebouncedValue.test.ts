import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

function mount(initial: string, delayMs = 300) {
  return renderHook(({ value }) => useDebouncedValue(value, delayMs), { initialProps: { value: initial } });
}

describe("useDebouncedValue", () => {
  it("starts with the value it is given", () => {
    const { result } = mount("a");

    expect(result.current).toBe("a");
  });

  it("keeps the old value until the pause has passed", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(299);
    });

    expect(result.current).toBe("a");
  });

  it("takes the new value at 300 ms", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current).toBe("b");
  });

  it("two changes in quick succession give one update, for the last", () => {
    const seen: string[] = [];
    const { result, rerender } = renderHook(
      ({ value }) => {
        const debounced = useDebouncedValue(value, 300);
        seen.push(debounced);
        return debounced;
      },
      { initialProps: { value: "a" } },
    );

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender({ value: "c" });
    act(() => {
      vi.advanceTimersByTime(299);
    });
    // 499 ms after the first change, only 299 after the last: still the first value.
    expect(result.current).toBe("a");
    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(result.current).toBe("c");
    expect(seen).not.toContain("b");
  });

  it("uses the delay it is given", () => {
    const { result, rerender } = mount("a", 50);

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(49);
    });
    expect(result.current).toBe("a");
    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(result.current).toBe("b");
  });

  it("leaves no timer behind when it unmounts", () => {
    const { rerender, unmount } = mount("a");

    rerender({ value: "b" });
    expect(vi.getTimerCount()).toBe(1);
    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
