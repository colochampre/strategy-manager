import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

/** Five years: 2026 (3 months), 2025 and 2024 (all 12 at 1%), 2023 (2 months), 2022 (1 month). */
function fiveYears(): MonthReturn[] {
  const full = (year: number) => Array.from({ length: 12 }, (_, i) => month(year, i + 1, "0.0100000000"));
  return [
    month(2022, 6, "-0.0500000000"),
    month(2023, 1, "0.0200000000"),
    month(2023, 2, "0.0200000000"),
    ...full(2024),
    ...full(2025),
    month(2026, 1, "0.0310000000"),
    month(2026, 2, "0.0100000000"),
    month(2026, 3, "0.0100000000"),
  ];
}

function rowYears(): string[] {
  return screen.getAllByRole("rowheader").map((node) => node.textContent ?? "");
}

function toggle(name: string) {
  return screen.queryByRole("button", { name });
}

describe("the earlier years toggle (decision 34)", () => {
  it("shows the three most recent UTC years and hides the rest", () => {
    render(<MonthlyGrid monthly={fiveYears()} />);
    expect(rowYears()).toEqual(["2026", "2025", "2024"]);
    expect(screen.queryByTestId("year-2023")).toBeNull();
    expect(screen.queryByTestId("month-2022-6")).toBeNull();
  });

  it("offers a real button, collapsed, with a 44 px target", () => {
    render(<MonthlyGrid monthly={fiveYears()} />);
    const button = toggle("Show earlier years");
    expect(button).toBeInTheDocument();
    expect(button!.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveClass("min-h-11");
  });

  it("reveals the older years in place, most recent first, and collapses them again", () => {
    render(<MonthlyGrid monthly={fiveYears()} />);
    fireEvent.click(screen.getByRole("button", { name: "Show earlier years" }));

    expect(rowYears()).toEqual(["2026", "2025", "2024", "2023", "2022"]);
    const collapse = toggle("Hide earlier years");
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    expect(toggle("Show earlier years")).toBeNull();

    fireEvent.click(collapse!);
    expect(rowYears()).toEqual(["2026", "2025", "2024"]);
    expect(toggle("Show earlier years")).toHaveAttribute("aria-expanded", "false");
  });

  it("controls the table it reveals rows in", () => {
    render(<MonthlyGrid monthly={fiveYears()} />);
    const button = screen.getByRole("button", { name: "Show earlier years" });
    const controlled = document.getElementById(button.getAttribute("aria-controls") ?? "");
    expect(controlled).not.toBeNull();
    expect(within(controlled!).getByRole("table")).toBeInTheDocument();
  });

  it("has no toggle at three years or fewer", () => {
    render(<MonthlyGrid monthly={fiveYears().filter((entry) => entry.year >= 2024)} />);
    expect(rowYears()).toEqual(["2026", "2025", "2024"]);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts the three latest years that have a closed month, not three calendar years", () => {
    render(<MonthlyGrid monthly={[month(2026, 1, "0.01"), month(2023, 1, "0.01"), month(2020, 1, "0.01"), month(2015, 1, "0.01")]} />);
    expect(rowYears()).toEqual(["2026", "2023", "2020"]);
    expect(toggle("Show earlier years")).toBeInTheDocument();
  });

  it("keeps each year's total over all of its months, visible or revealed", () => {
    render(<MonthlyGrid monthly={fiveYears()} />);
    // 1.01^12 - 1 = 12.68%: every month of 2024 counts, though 2023 and 2022 are hidden.
    expect(screen.getByTestId("year-2024")).toHaveTextContent("+12.7%");
    expect(screen.getByTestId("year-2026")).toHaveTextContent("+5.2%");
    fireEvent.click(screen.getByRole("button", { name: "Show earlier years" }));
    expect(screen.getByTestId("year-2023")).toHaveTextContent("+4.0%");
    expect(screen.getByTestId("year-2022")).toHaveTextContent("-5.0%");
  });

  it("is labelled in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(<MonthlyGrid monthly={fiveYears()} />);
    fireEvent.click(screen.getByRole("button", { name: "Mostrar años anteriores" }));
    expect(toggle("Ocultar años anteriores")).toHaveAttribute("aria-expanded", "true");
  });
});

describe("the grid at narrow widths", () => {
  it("keeps its rows compact so three years fit under the chart", () => {
    render(<MonthlyGrid monthly={[month(2026, 1, "0.0310000000"), month(2026, 2, "0.0000000000")]} />);
    expect(screen.getByTestId("month-2026-1")).toHaveClass("h-8");
    expect(screen.getByTestId("month-2026-2")).toHaveClass("h-8");
    expect(screen.getByTestId("month-2026-3")).toHaveClass("h-8");
  });

  it("scrolls sideways inside a wrapper instead of squeezing its figures together", () => {
    render(<MonthlyGrid monthly={[month(2026, 1, "0.0310000000")]} />);
    const table = screen.getByRole("table");
    // 13 columns of figures need a floor width; below it the wrapper scrolls, like the chart's.
    expect(table).toHaveClass("min-w-[42rem]");
    expect(table.parentElement).toHaveClass("overflow-x-auto");
  });
});
