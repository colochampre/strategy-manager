import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_SORT } from "@/features/strategies/card-sort";
import type { CardSort } from "@/features/strategies/card-sort";
import { SortControl } from "@/features/strategies/SortControl";

function draw(sort: CardSort = DEFAULT_SORT) {
  const onChange = vi.fn();
  render(<SortControl sort={sort} onChange={onChange} />);
  return { onChange, group: screen.getByRole("group", { name: "Sort by" }) };
}

describe("the sort control", () => {
  it("offers the five keys in order, as buttons in one named group", () => {
    const { group } = draw();

    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Age",
      "Closed trades",
      "Return",
      "Subscribers",
      "Capital",
    ]);
  });

  it("presses only the active key, and says its direction to assistive tech", () => {
    const { group } = draw({ key: "return", direction: "desc" });

    const pressed = within(group).getAllByRole("button", { pressed: true });
    expect(pressed).toHaveLength(1);
    expect(pressed[0]).toHaveAccessibleName("Return, descending");
    expect(within(group).getByRole("button", { name: "Age" })).toHaveAttribute("aria-pressed", "false");
  });

  it("says ascending when the active key runs ascending", () => {
    const { group } = draw({ key: "capital", direction: "asc" });

    expect(within(group).getByRole("button", { pressed: true })).toHaveAccessibleName("Capital, ascending");
  });

  it("draws a down arrow on a descending key and an up arrow on an ascending one", () => {
    const { group } = draw({ key: "trades", direction: "desc" });
    expect(within(group).getByRole("button", { pressed: true }).querySelector("svg.lucide-arrow-down")).not.toBeNull();
  });

  it("draws an up arrow on an ascending key", () => {
    const { group } = draw({ key: "trades", direction: "asc" });
    expect(within(group).getByRole("button", { pressed: true }).querySelector("svg.lucide-arrow-up")).not.toBeNull();
  });

  it("draws no arrow on a key that is not active", () => {
    const { group } = draw();

    expect(within(group).getByRole("button", { name: "Age" }).querySelector("svg")).toBeNull();
  });

  it("hands the chosen key to its owner", () => {
    const { group, onChange } = draw();

    fireEvent.click(within(group).getByRole("button", { name: "Subscribers" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("subscribers");
  });

  it("hands the active key too, so a second click can flip it", () => {
    const { group, onChange } = draw();

    fireEvent.click(within(group).getByRole("button", { name: "Return, descending" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("return");
  });
});
