import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MonthlyCard } from "@/features/overview/MonthlyCard";
import type { Excluded, MonthReturn } from "@/shared/api/types";
import i18n from "@/shared/i18n";

const MONTHLY: MonthReturn[] = [{ year: 2026, month: 9, return: "0.0310000000" }];
const NOTHING_EXCLUDED: Excluded = {
  open_trade_count: 0,
  rehearsal_fill_count: 0,
  no_capital_at_open: 0,
  unconverted_fee: 0,
  unresolved_allocation_count: 0,
};

describe("MonthlyCard", () => {
  it("is the dashboard's Monthly performance card, with the median month beside the title (L29, L35)", () => {
    render(<MonthlyCard monthly={MONTHLY} excluded={NOTHING_EXCLUDED} />);
    const card = screen.getByRole("region", { name: "Monthly performance" });
    expect(within(card).getByRole("heading", { level: 2, name: "Monthly performance" })).toBeInTheDocument();
    expect(within(card).getByTestId("monthly-median").textContent).toBe("Median +3.1% · 1 month");
    expect(within(card).queryByText(/Fixed range/)).toBeNull();
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

function months(...values: string[]): MonthReturn[] {
  return values.map((value, index) => ({ year: 2026, month: index + 1, return: value }));
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

// The median month and the scale behind an (i), in place of the fixed ±15% range (L35).
describe("MonthlyCard median and colour scale", () => {
  it("writes the middle month of an odd count, which one large month does not pull", () => {
    render(<MonthlyCard monthly={months("0.0100000000", "0.4000000000", "-0.0200000000")} excluded={NOTHING_EXCLUDED} />);
    expect(screen.getByTestId("monthly-median").textContent).toBe("Median +1.0% · 3 months");
  });

  it("writes the mean of the two middle months of an even count", () => {
    render(
      <MonthlyCard
        monthly={months("0.0100000000", "0.0300000000", "-0.0500000000", "0.0800000000")}
        excluded={NOTHING_EXCLUDED}
      />,
    );
    expect(screen.getByTestId("monthly-median").textContent).toBe("Median +2.0% · 4 months");
  });

  it("is written in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(<MonthlyCard monthly={months("0.0100000000", "-0.0300000000")} excluded={NOTHING_EXCLUDED} />);
    expect(screen.getByTestId("monthly-median").textContent).toBe("Mediana -1,0% · 2 meses");
  });

  it("tells the grid's scale behind the (i): the step of a shade and how far the six reach", () => {
    render(<MonthlyCard monthly={months("0.0600000000", "-0.0200000000")} excluded={NOTHING_EXCLUDED} />);
    fireEvent.click(screen.getByRole("button", { name: "About the colour scale" }));
    expect(
      screen.getByText(
        "Each shade is 1 point of return, up to ±6%. The scale adapts to this grid's largest month, so two grids are not coloured alike.",
      ),
    ).toBeVisible();
  });

  it("writes a quarter point step with its decimals", () => {
    render(<MonthlyCard monthly={months("0.0750000000")} excluded={NOTHING_EXCLUDED} />);
    fireEvent.click(screen.getByRole("button", { name: "About the colour scale" }));
    expect(screen.getByText(/^Each shade is 1\.25 points of return, up to ±7\.5%\./)).toBeVisible();
  });

  it("draws neither the median nor the (i) when there is no month, or a month cannot be read", () => {
    const { unmount } = render(<MonthlyCard monthly={[]} excluded={NOTHING_EXCLUDED} />);
    expect(screen.queryByTestId("monthly-median")).toBeNull();
    expect(screen.queryByRole("button", { name: "About the colour scale" })).toBeNull();
    unmount();

    render(<MonthlyCard monthly={months("0.0100000000", "not a number")} excluded={NOTHING_EXCLUDED} />);
    expect(screen.queryByTestId("monthly-median")).toBeNull();
    expect(screen.queryByRole("button", { name: "About the colour scale" })).toBeNull();
  });
});
