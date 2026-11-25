import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MonthlyCard } from "@/features/overview/MonthlyCard";
import type { Excluded, MonthReturn } from "@/shared/api/types";

const MONTHLY: MonthReturn[] = [{ year: 2026, month: 9, return: "0.0310000000" }];
const NOTHING_EXCLUDED: Excluded = {
  open_trade_count: 0,
  rehearsal_fill_count: 0,
  no_capital_at_open: 0,
  unconverted_fee: 0,
  unresolved_allocation_count: 0,
};

describe("MonthlyCard", () => {
  it("is the dashboard's Monthly performance card, with its fixed scale beside the title (L29)", () => {
    render(<MonthlyCard monthly={MONTHLY} excluded={NOTHING_EXCLUDED} />);
    const card = screen.getByRole("region", { name: "Monthly performance" });
    expect(within(card).getByRole("heading", { level: 2, name: "Monthly performance" })).toBeInTheDocument();
    expect(within(card).getByText("Fixed range of ±15%")).toBeInTheDocument();
    expect(within(card).getByRole("table", { name: "Monthly performance" })).toBeInTheDocument();
    expect(within(card).getByTestId("monthly-summary")).toBeInTheDocument();
  });

  it("draws the summary line right under the grid, with no gap between them (L29)", () => {
    render(<MonthlyCard monthly={MONTHLY} excluded={NOTHING_EXCLUDED} />);
    const summary = screen.getByTestId("monthly-summary");
    const body = summary.parentElement as HTMLElement;
    expect(body).toContainElement(screen.getByRole("table"));
    expect(body.className).not.toMatch(/\bgap-/);
  });
});
