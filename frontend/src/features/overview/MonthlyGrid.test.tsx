import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import type { MonthReturn } from "@/shared/api/types";
import i18n from "@/shared/i18n";

function month(year: number, m: number, value: string): MonthReturn {
  return { year, month: m, return: value };
}

/** The middle of band `k` (1 to 6): bands are 2.5 points wide. */
function bandValue(k: number, sign: 1 | -1 = 1): string {
  return String(sign * (k - 0.5) * 0.025);
}

function cell(name: RegExp | string) {
  return screen.getByRole("cell", { name });
}

function bandClasses(element: HTMLElement): string[] {
  return element.className.match(/\bbg-(?:gain|loss)-\d\b/g) ?? [];
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("MonthlyGrid", () => {
  it("test_band_maps_to_gain_or_loss_utility_class_by_sign_and_magnitude", () => {
    const cases: Array<[number, string, string]> = [
      [1, "0.0041000000", "bg-gain-1"],
      [2, "0.0310000000", "bg-gain-2"],
      // 7.5% exactly is band 3, not 4: float noise must not push it over the edge.
      [3, "0.0750000000", "bg-gain-3"],
      [4, "0.0751000000", "bg-gain-4"],
      [5, "0.1100000000", "bg-gain-5"],
      [6, "0.1300000000", "bg-gain-6"],
      [7, "-0.0190000000", "bg-loss-1"],
      [8, "-0.0251000000", "bg-loss-2"],
      [9, "-0.0750000000", "bg-loss-3"],
      [10, "-0.0760000000", "bg-loss-4"],
      [11, "-0.1200000000", "bg-loss-5"],
      [12, "-0.2000000000", "bg-loss-6"],
    ];
    render(<MonthlyGrid monthly={cases.map(([m, value]) => month(2026, m, value))} />);
    for (const [m, value, expected] of cases) {
      const element = screen.getByTestId(`month-2026-${m}`);
      // Exactly one band class, and it is the expected one: the sign decides gain or loss.
      expect(bandClasses(element), value).toEqual([expected]);
    }
  });

  it("colours exactly zero with the neutral base, not with a gain or loss band", () => {
    render(<MonthlyGrid monthly={[month(2026, 3, "0.0000000000")]} />);
    const element = screen.getByTestId("month-2026-3");
    expect(element).toHaveClass("bg-rule-soft");
    expect(bandClasses(element)).toEqual([]);
    expect(element).toHaveTextContent("0.0");
  });

  it("test_month_with_no_closed_trade_renders_dashed_empty_cell", () => {
    render(<MonthlyGrid monthly={[month(2026, 3, "0.0000000000"), month(2026, 4, "0.0310000000")]} />);
    const empty = screen.getByTestId("month-2026-1");
    expect(empty).toHaveClass("border", "border-dashed", "border-rule");
    expect(empty).toBeEmptyDOMElement();
    expect(bandClasses(empty)).toEqual([]);
    expect(empty).toHaveAccessibleName("January 2026: no closed trades");

    // A month at exactly 0% closed trades and is NOT the empty cell.
    const flat = screen.getByTestId("month-2026-3");
    expect(flat).not.toHaveClass("border-dashed");
    expect(flat).toHaveTextContent("0.0");
    expect(flat).toHaveAccessibleName("March 2026: 0.0%");
  });

  it("test_bands_4_to_6_use_text_ground_for_contrast", () => {
    const monthly = [1, 2, 3, 4, 5, 6].flatMap((k) => [
      month(2026, k, bandValue(k)),
      month(2025, k, bandValue(k, -1)),
    ]);
    render(<MonthlyGrid monthly={monthly} />);
    for (const year of [2026, 2025]) {
      for (const k of [1, 2, 3]) {
        const element = screen.getByTestId(`month-${year}-${k}`);
        expect(element).not.toHaveClass("text-ground");
        expect(element).not.toHaveClass("font-semibold");
      }
      for (const k of [4, 5, 6]) {
        const element = screen.getByTestId(`month-${year}-${k}`);
        expect(element, `${year}-${k}`).toHaveClass("text-ground", "font-semibold");
      }
    }
  });

  it("shows one row per UTC year, most recent first, months in their own column", () => {
    render(
      <MonthlyGrid
        monthly={[month(2025, 12, "0.0100000000"), month(2026, 1, "0.0310000000"), month(2024, 5, "-0.0100000000")]}
      />,
    );
    const years = screen.getAllByRole("rowheader").map((node) => node.textContent);
    expect(years).toEqual(["2026", "2025", "2024"]);
    expect(cell("January 2026: +3.1%")).toHaveTextContent("+3.1");
    // The value is written without the percent sign: the cell is narrow on a phone.
    expect(cell("January 2026: +3.1%")).not.toHaveTextContent("%");
    const header = screen.getAllByRole("columnheader").map((node) => node.textContent);
    expect(header).toEqual(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D", "Year"]);
  });

  it("writes the compounded year return, coloured by sign, from the server's months", () => {
    render(
      <MonthlyGrid
        monthly={[
          month(2026, 1, "0.1000000000"),
          month(2026, 2, "0.1000000000"),
          month(2025, 1, "-0.1000000000"),
          month(2025, 2, "0.0500000000"),
        ]}
      />,
    );
    // 1.1 * 1.1 - 1 = 21%; 0.9 * 1.05 - 1 = -5.5%.
    const gain = screen.getByTestId("year-2026");
    expect(gain).toHaveTextContent("+21.0%");
    expect(gain).toHaveClass("text-gain", "font-semibold");
    const loss = screen.getByTestId("year-2025");
    expect(loss).toHaveTextContent("-5.5%");
    expect(loss).toHaveClass("text-loss", "font-semibold");
    expect(gain.className).not.toMatch(/\bbg-/);
  });

  it("names each month by its UTC calendar month, whatever the viewer's time zone", () => {
    const originalTz = process.env.TZ;
    // West of UTC, midnight UTC on the 1st is still the last day of the month before.
    process.env.TZ = "America/Los_Angeles";
    try {
      render(<MonthlyGrid monthly={[month(2026, 1, "0.0310000000"), month(2026, 12, "0.0100000000")]} />);
      expect(screen.getByRole("columnheader", { name: "January" })).toHaveTextContent("J");
      expect(screen.getByRole("columnheader", { name: "December" })).toHaveTextContent("D");
      expect(cell("January 2026: +3.1%")).toBeInTheDocument();
      expect(cell("December 2026: +1.0%")).toBeInTheDocument();
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
  });

  it("is a labelled table: a title, column headers per month and a row header per year", () => {
    render(<MonthlyGrid monthly={[month(2026, 1, "0.0310000000")]} />);
    expect(screen.getByRole("heading", { name: "Month by month", level: 2 })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Month by month" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(13);
    expect(within(table).getByRole("columnheader", { name: "Year" })).toBeInTheDocument();
    expect(within(table).getByRole("rowheader", { name: "2026" })).toBeInTheDocument();
  });

  it("reads every word and month name in the active language", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(<MonthlyGrid monthly={[month(2026, 7, "0.0310000000"), month(2026, 8, "-0.0100000000")]} />);
    expect(screen.getByRole("heading", { name: "Mes a mes" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Año" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "julio" })).toBeInTheDocument();
    expect(screen.getByTestId("month-2026-7")).toHaveAccessibleName(/^julio 2026: \+3,1/);
    expect(screen.getByTestId("month-2026-1")).toHaveAccessibleName("enero 2026: sin operaciones cerradas");
  });

  it("shows a defined empty state, not a table of dashed cells, when nothing has closed", () => {
    render(<MonthlyGrid monthly={[]} />);
    expect(screen.getByText("No closed months yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an alert rather than NaN when a value cannot be read", () => {
    const { container } = render(<MonthlyGrid monthly={[month(2026, 1, "abc")]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The monthly returns could not be read.");
    expect(container).not.toHaveTextContent("NaN");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an alert for a month that is not a calendar month", () => {
    render(<MonthlyGrid monthly={[month(2026, 13, "0.01")]} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
