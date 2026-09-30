import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RangeSelector } from "@/features/overview/RangeSelector";
import i18n from "@/shared/i18n";

function pressed(): string[] {
  return screen
    .getAllByRole("button")
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.textContent ?? "");
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("RangeSelector", () => {
  it("test_default_range_is_30d_pressed_state_aria_pressed_44px_minimum_touch_target", () => {
    render(<RangeSelector onChange={() => undefined} />);
    const group = screen.getByRole("group", { name: "Range" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["7D", "30D", "90D", "1Y", "All"]);

    // Exactly one range is pressed, 30D, and every other button says it is not.
    expect(pressed()).toEqual(["30D"]);
    for (const button of buttons) {
      expect(button).toHaveAttribute("aria-pressed", button.textContent === "30D" ? "true" : "false");
      // 44 px on both axes (Tailwind's 11 is 2.75rem), the touch target of every mockup.
      expect(button).toHaveClass("min-h-11", "min-w-11");
      expect(button).toHaveAttribute("type", "button");
    }
    expect(screen.getByRole("button", { name: "30D" })).toHaveClass("bg-panel-2", "text-ink");
    expect(screen.getByRole("button", { name: "7D" })).toHaveClass("text-ink-2");
    expect(screen.getByRole("button", { name: "7D" })).not.toHaveClass("bg-panel-2");
  });

  it("wraps and keeps its width instead of clipping a button when its row is tight", () => {
    render(<RangeSelector onChange={() => undefined} />);
    const group = screen.getByRole("group", { name: "Range" });
    expect(group).toHaveClass("flex-wrap", "shrink-0", "max-w-full");
    expect(group.className).not.toMatch(/whitespace-nowrap|flex-nowrap/);
    for (const button of within(group).getAllByRole("button")) {
      expect(button).toHaveClass("min-h-11", "min-w-11");
    }
  });

  it("reports the clicked range by its server name and moves the pressed state to it", () => {
    const onChange = vi.fn();
    render(<RangeSelector onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "90D" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("90D");
    expect(pressed()).toEqual(["90D"]);
  });

  it("does not move the pressed state when the owner controls it", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RangeSelector value="7D" onChange={onChange} />);
    expect(pressed()).toEqual(["7D"]);
    fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    expect(onChange).toHaveBeenCalledWith("1Y");
    expect(pressed()).toEqual(["7D"]);
    rerender(<RangeSelector value="1Y" onChange={onChange} />);
    expect(pressed()).toEqual(["1Y"]);
  });

  it("labels the group and the ranges in the active language, but reports server names", async () => {
    await act(() => i18n.changeLanguage("es"));
    const onChange = vi.fn();
    render(<RangeSelector onChange={onChange} />);
    const group = screen.getByRole("group", { name: "Rango" });
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "7D",
      "30D",
      "90D",
      "1A",
      "Todo",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Todo" }));
    expect(onChange).toHaveBeenCalledWith("All");
  });
});
