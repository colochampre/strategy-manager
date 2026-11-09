import { act, createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReturnChart } from "@/features/overview/ReturnChart";
import type { RangeName } from "@/features/overview/RangeSelector";
import type { CurvePoint } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/**
 * The plot at the default width (796, what jsdom falls back to): x runs 44 to 790, the
 * box is 280 tall, the zero line sits at 12 + 0.62 * 244 = 163.28, the top of the upper
 * band is y 12 and the bottom of the lower band is y 256.
 */
const LEFT = 44;
const RIGHT = 790;
const TOP = 12;
const WATER_Y = 163.28;
const UPPER = 151.28;
const LOWER = 92.72;

function day(offset: number, base = Date.UTC(2026, 6, 1)): string {
  return new Date(base + offset * 86_400_000).toISOString().slice(0, 10);
}

function point(date: string, index: number, drawdown: number): CurvePoint {
  return { date, daily_return: "0", index: String(index), drawdown: String(drawdown) };
}

/** The point each command of `M x,y L x,y C c1 c2 x,y ...` arrives at (a curve's control points skipped). */
function coordinates(d: string): Array<[number, number]> {
  return [...d.matchAll(/[MLC]((?:\s*-?[\d.]+,-?[\d.]+)+)/g)].map((m) => {
    const pairs = [...m[1]!.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)];
    const last = pairs[pairs.length - 1]!;
    return [Number(last[1]), Number(last[2])];
  });
}

function attr(testId: string, name: string): string {
  const element = screen.getByTestId(testId);
  return element.getAttribute(name) ?? "";
}

/** 2026-09-30 12:00 UTC: the "now" every range window ends on. */
const AS_OF = Date.UTC(2026, 8, 30, 12, 0, 0);

function renderChart(curve: CurvePoint[], range: RangeName = "All", asOf = AS_OF) {
  return render(<ReturnChart curve={curve} range={range} asOf={asOf} />);
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("ReturnChart", () => {
  it("test_renders_polyline_and_drawdown_path_from_curve_prop", () => {
    // Cumulative return 0, 10%, 30%, 20%; the last day is 7.69% under its peak.
    const curve = [
      point("2026-07-01", 1, 0),
      point("2026-07-02", 1.1, 0),
      point("2026-07-03", 1.3, 0),
      point("2026-07-04", 1.2, -1 / 13),
    ];
    // Read on the day of the last close, so the axis, which runs to today, ends on it.
    renderChart(curve, "All", Date.UTC(2026, 6, 4, 12));

    const line = coordinates(attr("return-curve", "d"));
    expect(line).toHaveLength(4);
    expect(line[0]![0]).toBeCloseTo(LEFT, 1);
    expect(line[3]![0]).toBeCloseTo(RIGHT, 1);
    // Upper extreme 30% is the top of the plot; 0 is the waterline; 10% a third of the way.
    expect(line[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(line[1]![1]).toBeCloseTo(WATER_Y - UPPER / 3, 1);
    expect(line[2]![1]).toBeCloseTo(TOP, 1);
    expect(line[3]![1]).toBeCloseTo(WATER_Y - (UPPER * 2) / 3, 1);

    const fill = attr("drawdown-fill", "d");
    const fillPoints = coordinates(fill);
    // From the waterline at the first x, along the drawdown, back to the waterline.
    expect(fill.trim().endsWith("Z")).toBe(true);
    expect(fillPoints[0]![0]).toBeCloseTo(LEFT, 1);
    expect(fillPoints[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(fillPoints[fillPoints.length - 1]![0]).toBeCloseTo(RIGHT, 1);
    expect(fillPoints[fillPoints.length - 1]![1]).toBeCloseTo(WATER_Y, 1);
    // A 7.69% drawdown is 77% of the floored 10% lower band.
    expect(Math.max(...fillPoints.map(([, y]) => y))).toBeCloseTo(WATER_Y + LOWER * (1 / 13 / 0.1), 1);

    const edge = coordinates(attr("drawdown-edge", "d"));
    expect(edge).toHaveLength(4);
    expect(edge[3]![1]).toBeCloseTo(WATER_Y + LOWER * (1 / 13 / 0.1), 1);

    const waterline = screen.getByTestId("waterline");
    expect(Number(waterline.getAttribute("y1"))).toBeCloseTo(WATER_Y, 1);
    expect(Number(waterline.getAttribute("y2"))).toBeCloseTo(WATER_Y, 1);
  });

  it("draws the colours through utility classes only", () => {
    renderChart([point("2026-07-01", 1, 0), point("2026-07-02", 1.05, -0.02)]);
    expect(screen.getByTestId("return-curve")).toHaveClass("stroke-gain", "fill-none");
    expect(screen.getByTestId("drawdown-fill")).toHaveClass("fill-loss/20");
    expect(screen.getByTestId("drawdown-edge")).toHaveClass("stroke-loss", "fill-none");
    expect(screen.getByTestId("waterline")).toHaveClass("stroke-rule-strong");

    const svg = screen.getByRole("img");
    for (const element of [svg, ...svg.querySelectorAll("*")]) {
      for (const name of ["fill", "stroke", "style"]) {
        // `none` is a keyword, not a colour, and `url(#id)` points at the gradient, whose own
        // colour is a class; nothing may carry a colour attribute.
        expect(element.getAttribute(name) ?? "none").toMatch(/^(none|url\(#[^)]+\))$/);
      }
      expect(element.getAttribute("class") ?? "").not.toMatch(/#[0-9a-f]{3,8}|var\(/i);
    }
  });

  it("draws gridlines at each tick of both bands, with labels in a left gutter", () => {
    renderChart([point("2026-07-01", 1, 0), point("2026-07-02", 1.3, -0.02)]);
    const labels = screen.getAllByTestId("y-label").map((node) => node.textContent);
    expect(labels).toEqual(["+30%", "+20%", "+10%", "0%", "−5%", "−10%"]);
    // Upper band: 10% steps to 30%; lower band (floored to 10%): 5% steps.
    const grid = screen.getAllByTestId("gridline").map((line) => Number(line.getAttribute("y1")));
    expect(grid).toHaveLength(5);
    expect(grid[0]).toBeCloseTo(TOP, 1);
    expect(grid[1]).toBeCloseTo(WATER_Y - (UPPER * 2) / 3, 1);
    expect(grid[2]).toBeCloseTo(WATER_Y - UPPER / 3, 1);
    expect(grid[3]).toBeCloseTo(WATER_Y + LOWER / 2, 1);
    expect(grid[4]).toBeCloseTo(WATER_Y + LOWER, 1);
    for (const line of screen.getAllByTestId("gridline")) {
      expect(line).toHaveClass("stroke-rule-soft");
      expect(Number(line.getAttribute("x1"))).toBe(LEFT);
    }
  });

  it("puts a month label on the first UTC day of each month, whatever the viewer's time zone", () => {
    const originalTz = process.env.TZ;
    // West of UTC, midnight UTC on the 1st is still the last day of the month before.
    process.env.TZ = "America/Los_Angeles";
    try {
      assertMonthLabels();
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
  });

  function assertMonthLabels() {
    // Over three months, so the All range names month starts between its ends.
    const curve = [
      point("2026-05-14", 1, 0),
      point("2026-08-20", 1.05, 0),
      point("2026-09-10", 1.1, 0),
    ];
    renderChart(curve, "All", Date.UTC(2026, 8, 10, 12));
    const ticks = screen.getAllByTestId("month-label");
    expect(ticks.map((node) => node.textContent)).toEqual(["Jun", "Jul", "Aug", "Sep"]);
    // 2026-06-01 is 18 of 119 days into the span.
    expect(Number(ticks[0]!.getAttribute("x"))).toBeCloseTo(LEFT + ((RIGHT - LEFT) * 18) / 119, 1);
  }

  it("drops month labels that would overprint the previous one on a long history", () => {
    // Four years in 746 units is about 15 units a month: labels need 28 to stay legible.
    renderChart([point("2023-01-01", 1, 0), point("2026-12-31", 1.5, 0)]);
    const xs = screen.getAllByTestId("month-label").map((n) => Number(n.getAttribute("x")));
    expect(xs.length).toBeGreaterThan(10);
    expect(xs.length).toBeLessThan(48);
    for (let i = 1; i < xs.length; i += 1) expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(28);
  });

  it("draws a negative cumulative return in the lower band, on the same scale as the drawdown", () => {
    const curve = [point("2026-07-01", 1, 0), point("2026-07-02", 0.75, -0.25)];
    renderChart(curve);
    const line = coordinates(attr("return-curve", "d"));
    expect(line[1]![1]).toBeCloseTo(WATER_Y + LOWER, 1);
    expect(coordinates(attr("drawdown-edge", "d"))[1]![1]).toBeCloseTo(WATER_Y + LOWER, 1);
    // Nothing above the waterline, so the upper band keeps its 10% floor.
    expect(screen.getAllByTestId("y-label").map((node) => node.textContent)).toEqual([
      "+10%",
      "+5%",
      "0%",
      "−5%",
      "−10%",
      "−15%",
      "−20%",
      "−25%",
    ]);
  });

  it("keeps a flat series on the waterline without an invalid coordinate", () => {
    renderChart([point("2026-07-01", 1, 0), point("2026-07-02", 1, 0)]);
    const d = attr("return-curve", "d");
    expect(d).not.toMatch(/NaN|Infinity/);
    for (const [, y] of coordinates(d)) expect(y).toBeCloseTo(WATER_Y, 1);
  });

  it("draws a single day as a point at the centre", () => {
    // Read that same day, with no origin: one day of axis, so the point sits in its middle.
    renderChart([point("2026-07-01", 1.1, 0)], "All", Date.UTC(2026, 6, 1, 12));
    const dot = screen.getByTestId("return-dot");
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo((LEFT + RIGHT) / 2, 1);
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(WATER_Y - UPPER, 1);
    expect(dot).toHaveClass("fill-gain");
    expect(attr("return-curve", "d")).not.toMatch(/NaN/);
  });

  it("test_empty_state_no_closed_trades_yet_when_curve_is_empty", () => {
    renderChart([]);
    expect(screen.getByText("No closed trades yet")).toBeInTheDocument();
    expect(screen.getByTestId("waterline")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.queryByTestId("return-curve")).toBeNull();
    expect(screen.queryByTestId("drawdown-fill")).toBeNull();
    expect(screen.queryByTestId("gridline")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // It is still the same labelled image, not an empty box.
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", en.overview.returnChart.ariaLabel);
  });

  it("test_all_draws_the_whole_series_on_the_axis_of_its_own_peak", () => {
    // 90 days with the peak and the deepest drawdown in the FIRST month, then flat.
    const curve = Array.from({ length: 90 }, (_, i) =>
      i === 5
        ? point(day(i), 1.4, 0)
        : i === 8
          ? point(day(i), 1.2, -0.14)
          : point(day(i), i < 5 ? 1 + i * 0.08 : 1.2, i < 8 ? 0 : -0.1),
    );
    // Read on the day of the last close (2026-09-28), so the axis ends on it.
    renderChart(curve, "All", Date.UTC(2026, 8, 28, 12));

    const line = coordinates(attr("return-curve", "d"));
    // Every day is drawn, from the first to the last.
    expect(line).toHaveLength(90);
    expect(line[0]![0]).toBeCloseTo(LEFT, 1);
    expect(line[89]![0]).toBeCloseTo(RIGHT, 1);
    // The axis reaches the early 40% peak, and the series is not rebased.
    expect(Math.min(...line.map(([, y]) => y))).toBeCloseTo(TOP, 1);
    expect(screen.getAllByTestId("y-label").map((n) => n.textContent)).toContain("+40%");
    // There is no range control in the chart: the panel owns the selector.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(within(screen.getByRole("figure")).queryByText(/30D|7D|90D|1Y/)).toBeNull();
    const days = screen.getAllByTestId("day-label").map((n) => n.textContent);
    expect([days[0], days.at(-1)]).toEqual(["Jul 1", "Sep 28"]);
  });

  it("test_role_img_aria_label_from_i18n", async () => {
    renderChart([point("2026-07-01", 1, 0), point("2026-07-02", 1.1, 0)]);
    const svg = screen.getByRole("img");
    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(svg).toHaveAttribute("aria-label", en.overview.returnChart.ariaLabel);
    expect(en.overview.returnChart.ariaLabel.length).toBeGreaterThan(10);

    await act(() => i18n.changeLanguage("es"));
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", es.overview.returnChart.ariaLabel);
    expect(es.overview.returnChart.ariaLabel).not.toBe(en.overview.returnChart.ariaLabel);
    // The empty state and the caption are translated too.
    expect(screen.getByText(es.overview.returnChart.caption)).toBeInTheDocument();
  });

  it("draws in real pixels: the viewBox is the measured width by a fixed 280", () => {
    renderChart([]);
    const svg = screen.getByRole("img");
    // No measurement yet (jsdom has no layout): the default width stands in.
    expect(svg).toHaveAttribute("viewBox", "0 0 796 280");
    expect(svg).toHaveAttribute("height", "280");
    expect(svg).toHaveClass("block", "w-full");
    expect(svg).not.toHaveClass("h-auto");
    expect(svg).not.toHaveAttribute("preserveAspectRatio", "none");
    expect(svg).not.toHaveAttribute("width");
  });

  it("carries an action in its header, on the title's row, with the caption under the title", () => {
    render(
      <ReturnChart
        curve={[]}
        range="All"
        asOf={AS_OF}
        headerAction={<button type="button">pick</button>}
      />,
    );
    const header = screen.queryByTestId("chart-header");
    expect(header).toContainElement(screen.getByRole("button", { name: "pick" }));
    expect(header).toHaveClass("flex", "flex-wrap", "justify-between");
    const title = screen.getByRole("heading", { name: en.overview.returnChart.title });
    const caption = screen.getByText(en.overview.returnChart.caption);
    expect(title.parentElement).toBe(caption.parentElement);
    expect(title.parentElement).toHaveClass("flex-col");
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  it("keeps the action when the curve cannot be read", () => {
    const broken = [point("2026-07-01", 1, 0), { ...point("2026-07-02", 1.1, 0), index: "abc" }];
    render(<ReturnChart curve={broken} range="All" asOf={AS_OF} headerAction={<button type="button">pick</button>} />);
    expect(screen.queryByTestId("chart-header")).toContainElement(screen.getByRole("button", { name: "pick" }));
  });

  it("refuses to draw an unreadable curve instead of a silent wrong line", () => {
    const broken = [point("2026-07-01", 1, 0), { ...point("2026-07-02", 1.1, 0), index: "abc" }];
    renderChart(broken);
    expect(screen.getByRole("alert")).toHaveTextContent(en.overview.returnChart.unreadable);
    expect(screen.queryByTestId("return-curve")).toBeNull();
  });

  it("has a translated title and caption in both languages", () => {
    renderChart([]);
    expect(screen.getByRole("heading", { name: en.overview.returnChart.title })).toBeInTheDocument();
    expect(screen.getByText(en.overview.returnChart.caption)).toBeInTheDocument();
    expect(Object.keys(es.overview.returnChart).sort()).toEqual(Object.keys(en.overview.returnChart).sort());
  });

  it("shows the title it is given instead of the Overview's, keeping the caption, and also when the curve is unreadable", () => {
    const { rerender } = render(<ReturnChart curve={[]} range="All" asOf={AS_OF} title="Contribution of this strategy" />);
    expect(screen.getByRole("heading", { name: "Contribution of this strategy" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: en.overview.returnChart.title })).toBeNull();
    expect(screen.getByText(en.overview.returnChart.caption)).toBeInTheDocument();

    rerender(
      <ReturnChart curve={[point("2026-07-10", Number.NaN, 0)]} range="All" asOf={AS_OF} title="Contribution of this strategy" />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(en.overview.returnChart.unreadable);
    expect(screen.getByRole("heading", { name: "Contribution of this strategy" })).toBeInTheDocument();
  });
});

/**
 * One curve for every range. Today is 2026-09-30, so the windows start on
 * 7D 09-23, 30D 08-31, 90D 07-02, 1Y 2025-09-30. The peak (1.4) and the
 * index before the 30D window (1.2, on 08-25) are OUTSIDE it.
 */
const RANGE_CURVE = [
  point("2026-07-10", 1.4, 0),
  point("2026-08-25", 1.2, -1 / 7),
  point("2026-09-02", 1.26, -0.1),
  point("2026-09-10", 1.323, -0.055),
  point("2026-09-20", 1.2, -1 / 7),
  point("2026-09-28", 1.32, -0.057),
];

/** The x of a UTC day on a window that runs `from` to 2026-09-30. */
function windowX(from: string, date: string): number {
  const span = Date.UTC(2026, 8, 30) - Date.parse(from);
  return LEFT + ((Date.parse(date) - Date.parse(from)) / span) * (RIGHT - LEFT);
}

describe("a range window", () => {
  it("keeps only the days inside the window, placed on the window's own axis", () => {
    renderChart(RANGE_CURVE, "30D");
    const line = coordinates(attr("return-curve", "d"));
    expect(line).toHaveLength(4);
    expect(line[0]![0]).toBeCloseTo(windowX("2026-08-31", "2026-09-02"), 1);
    expect(line[3]![0]).toBeCloseTo(windowX("2026-08-31", "2026-09-28"), 1);
  });

  it("rebases on the last day before the window, so its first day is its own return", () => {
    renderChart(RANGE_CURVE, "30D");
    const line = coordinates(attr("return-curve", "d"));
    // Rebased on 1.2: +5%, +10.25%, 0%, +10%. The 10.25% peak tops the plot.
    const top = 0.1025;
    expect(line[0]![1]).toBeCloseTo(WATER_Y - (0.05 / top) * UPPER, 1);
    expect(line[1]![1]).toBeCloseTo(TOP, 1);
    expect(line[2]![1]).toBeCloseTo(WATER_Y, 1);
    expect(line[3]![1]).toBeCloseTo(WATER_Y - (0.1 / top) * UPPER, 1);
    // The 40% peak from before the window is gone from the axis.
    expect(screen.getAllByTestId("y-label").map((n) => n.textContent)).not.toContain("+40%");
  });

  it("measures the drawdown from the peak inside the window, not the one before it", () => {
    renderChart(RANGE_CURVE, "30D");
    const edge = coordinates(attr("drawdown-edge", "d"));
    // Inside the window the peak is 1.1025 (rebased): 09-20 sits 1 - 1/1.1025 under it.
    expect(edge[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(edge[2]![1]).toBeCloseTo(WATER_Y + LOWER * ((1 - 1 / 1.1025) / 0.1), 1);
    // The lower band keeps its 10% floor.
    expect(screen.getAllByTestId("y-label").map((n) => n.textContent)).toContain("−10%");
  });

  it("follows the range: pressing a shorter one redraws with fewer days", () => {
    const { rerender } = renderChart(RANGE_CURVE, "All");
    expect(coordinates(attr("return-curve", "d"))).toHaveLength(6);
    rerender(<ReturnChart curve={RANGE_CURVE} range="30D" asOf={AS_OF} />);
    expect(coordinates(attr("return-curve", "d"))).toHaveLength(4);
    rerender(<ReturnChart curve={RANGE_CURVE} range="7D" asOf={AS_OF} />);
    expect(coordinates(attr("return-curve", "d"))).toHaveLength(1);
  });

  it("draws one day in the window as a point, still on the rebased scale", () => {
    renderChart(RANGE_CURVE, "7D");
    // Base is 1.2 (09-20); 09-28 is 1.32, +10% exactly the floored band: the top of the plot.
    const dot = screen.getByTestId("return-dot");
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo(windowX("2026-09-23", "2026-09-28"), 1);
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(TOP, 1);
    expect(attr("return-curve", "d")).not.toMatch(/NaN/);
  });

  it("hands the last rebased value over for checks against the ledger line", () => {
    renderChart(RANGE_CURVE, "30D");
    expect(Number(attr("return-curve", "data-final-return"))).toBeCloseTo(1.32 / 1.2 - 1, 6);
    renderChart(RANGE_CURVE, "All");
    const all = screen.getAllByTestId("return-curve")[1]!;
    expect(Number(all.getAttribute("data-final-return"))).toBeCloseTo(0.32, 6);
  });

  it("shows a defined empty state, not an error and not a flat line, for a range without days", () => {
    renderChart([point("2026-07-01", 1.1, 0), point("2026-07-02", 1.2, 0)], "7D");
    expect(screen.getByText(en.overview.returnChart.emptyRange)).toBeInTheDocument();
    expect(en.overview.returnChart.emptyRange).toBe("No closed trades in this range");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("return-curve")).toBeNull();
    expect(screen.queryByTestId("drawdown-fill")).toBeNull();
    expect(screen.getByTestId("waterline")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", en.overview.returnChart.ariaLabel);
  });

  it("says no closed trades yet, whatever the range, when the whole curve is empty", () => {
    renderChart([], "7D");
    expect(screen.getByText(en.overview.returnChart.empty)).toBeInTheDocument();
    expect(screen.queryByText(en.overview.returnChart.emptyRange)).toBeNull();
  });

  it("translates the empty-range message", async () => {
    await act(() => i18n.changeLanguage("es"));
    renderChart([point("2026-07-01", 1.1, 0)], "7D");
    expect(screen.getByText(es.overview.returnChart.emptyRange)).toBeInTheDocument();
    expect(es.overview.returnChart.emptyRange).not.toBe(en.overview.returnChart.emptyRange);
  });
});

describe("the time axis ticks", () => {
  function labels(testId: string): string[] {
    return screen.queryAllByTestId(testId).map((node) => node.textContent ?? "");
  }

  it("puts a label on every UTC day of a 7D window", () => {
    renderChart(RANGE_CURVE, "7D");
    expect(labels("day-label")).toEqual([
      "Sep 23",
      "Sep 24",
      "Sep 25",
      "Sep 26",
      "Sep 27",
      "Sep 28",
      "Sep 29",
      "Sep 30",
    ]);
    expect(labels("month-label")).toEqual([]);
  });

  it("puts a label about every week of a 30D window", () => {
    renderChart(RANGE_CURVE, "30D");
    expect(labels("day-label")).toEqual(["Aug 31", "Sep 7", "Sep 14", "Sep 21", "Sep 28"]);
    expect(labels("month-label")).toEqual([]);
  });

  it.each([
    ["90D", ["Aug", "Sep"]],
    ["1Y", ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]],
  ] as const)("puts a label on each month start of a %s window", (range, expected) => {
    renderChart(RANGE_CURVE, range);
    expect(labels("month-label")).toEqual(expected);
    expect(labels("day-label")).toEqual([]);
  });

  it("names the first close and today for All when the curve has no origin", () => {
    renderChart(RANGE_CURVE, "All");
    const days = labels("day-label");
    expect([days[0], days.at(-1)]).toEqual(["Jul 10", "Sep 30"]);
    expect(labels("month-label")).toEqual([]);
  });

  it("names days in UTC whatever the viewer's time zone", () => {
    const originalTz = process.env.TZ;
    // West of UTC, midnight UTC on the 23rd is still the 22nd.
    process.env.TZ = "America/Los_Angeles";
    try {
      renderChart(RANGE_CURVE, "7D");
      expect(labels("day-label")[0]).toBe("Sep 23");
      expect(labels("day-label")[7]).toBe("Sep 30");
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
  });

  it("keeps the last label inside the drawing by anchoring it at its end", () => {
    renderChart(RANGE_CURVE, "7D");
    const all = screen.getAllByTestId("day-label");
    expect(Number(all[7]!.getAttribute("x"))).toBeCloseTo(RIGHT, 1);
    expect(all[7]).toHaveAttribute("text-anchor", "end");
    expect(all[3]).toHaveAttribute("text-anchor", "middle");
  });

  it("labels the days in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    renderChart(RANGE_CURVE, "7D");
    expect(labels("day-label")[0]).toBe("23 sept");
  });
});

describe("the origin and the All range's dates (decision 36)", () => {
  function labels(testId: string): string[] {
    return screen.queryAllByTestId(testId).map((node) => node.textContent ?? "");
  }

  /** The first trade opened on 2026-07-05 and closed on 07-10. */
  function renderWithOrigin(range: RangeName, origin: string | null = "2026-07-05") {
    return render(<ReturnChart curve={RANGE_CURVE} range={range} asOf={AS_OF} origin={origin} />);
  }

  it("starts the whole curve at 0 on the day its first trade opened, on the left edge", () => {
    renderWithOrigin("All");
    const line = coordinates(attr("return-curve", "d"));
    expect(line).toHaveLength(RANGE_CURVE.length + 1);
    expect(line[0]![0]).toBeCloseTo(LEFT, 1);
    expect(line[0]![1]).toBeCloseTo(WATER_Y, 1);
  });

  it("runs the All axis to today, so a quiet stretch since the last close shows as space", () => {
    renderWithOrigin("All");
    const line = coordinates(attr("return-curve", "d"));
    // 2026-07-05 to 2026-09-30 is 87 days; the last close, 09-28, is 85 of them in.
    expect(line[line.length - 1]![0]).toBeCloseTo(LEFT + ((RIGHT - LEFT) * 85) / 87, 1);
  });

  it("names the start and today on the All range, at its two edges", () => {
    renderWithOrigin("All");
    const days = screen.getAllByTestId("day-label");
    expect(days[0]!.textContent).toBe("Jul 5");
    expect(Number(days[0]!.getAttribute("x"))).toBeCloseTo(LEFT, 1);
    expect(days[days.length - 1]!.textContent).toBe("Sep 30");
    expect(Number(days[days.length - 1]!.getAttribute("x"))).toBeCloseTo(RIGHT, 1);
  });

  it("names the weeks between the ends of an All range under three months", () => {
    renderWithOrigin("All");
    expect(labels("day-label")).toEqual([
      "Jul 5",
      "Jul 12",
      "Jul 19",
      "Jul 26",
      "Aug 2",
      "Aug 9",
      "Aug 16",
      "Aug 23",
      "Aug 30",
      "Sep 6",
      "Sep 13",
      "Sep 20",
      "Sep 30",
    ]);
    expect(labels("month-label")).toEqual([]);
  });

  it("drops a week that would overprint today", () => {
    // 2026-07-05 to 09-28 is 85 days: the week of 09-27 falls one day before today.
    render(<ReturnChart curve={RANGE_CURVE} range="All" asOf={Date.UTC(2026, 8, 28, 12)} origin="2026-07-05" />);
    expect(labels("day-label").slice(-2)).toEqual(["Sep 20", "Sep 28"]);
  });

  it("drops a month start that would overprint the start, and names months beyond three", () => {
    // 2026-06-27 to 09-30 is 95 days: month starts. 07-01 is four days in, about 31
    // units: clear of a month label, but not of the wider date the start is written as.
    render(<ReturnChart curve={RANGE_CURVE} range="All" asOf={AS_OF} origin="2026-06-27" />);
    expect(labels("day-label")).toEqual(["Jun 27", "Sep 30"]);
    expect(labels("month-label")).toEqual(["Aug", "Sep"]);
  });

  it("starts a window that reaches back to the origin at 0 on it", () => {
    renderWithOrigin("90D");
    const line = coordinates(attr("return-curve", "d"));
    expect(line).toHaveLength(RANGE_CURVE.length + 1);
    expect(line[0]![0]).toBeCloseTo(windowX("2026-07-02", "2026-07-05"), 1);
    expect(line[0]![1]).toBeCloseTo(WATER_Y, 1);
  });

  it("draws a single close after its origin as a line from 0, not a lone point", () => {
    render(<ReturnChart curve={[point("2026-09-20", 1.05, 0)]} range="All" asOf={AS_OF} origin="2026-09-18" />);
    expect(coordinates(attr("return-curve", "d"))).toHaveLength(2);
    expect(screen.queryByTestId("return-dot")).toBeNull();
  });
});

/** A `ResizeObserver` the test drives by hand: `resizeTo` reports a new width to every observer. */
function stubResizeObserver() {
  const callbacks: Array<(entries: Array<{ contentRect: { width: number } }>) => void> = [];
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: (entries: Array<{ contentRect: { width: number } }>) => void) {
        callbacks.push(callback);
      }
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = disconnect;
    },
  );
  return {
    disconnect,
    resizeTo: (width: number) => {
      act(() => {
        for (const callback of callbacks) callback([{ contentRect: { width } }]);
      });
    },
  };
}

describe("the measured width", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const CURVE = [point("2026-07-01", 1, 0), point("2026-07-02", 1.1, 0), point("2026-07-03", 1.3, 0)];

  it("redraws at the new width while the height stays fixed", () => {
    const observer = stubResizeObserver();
    // Read on the day of the last close, so the last point sits on the right edge.
    renderChart(CURVE, "All", Date.UTC(2026, 6, 3, 12));
    const svg = screen.getByRole("img");
    expect(svg).toHaveAttribute("viewBox", "0 0 796 280");

    observer.resizeTo(1252);
    expect(svg).toHaveAttribute("viewBox", "0 0 1252 280");
    expect(svg).toHaveAttribute("height", "280");
    const wide = coordinates(attr("return-curve", "d"));
    expect(wide[0]![0]).toBeCloseTo(LEFT, 1);
    expect(wide[2]![0]).toBeCloseTo(1252 - 6, 1);
    // The vertical geometry does not move with the width.
    expect(wide[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(wide[2]![1]).toBeCloseTo(TOP, 1);
    for (const line of screen.getAllByTestId("gridline")) {
      expect(Number(line.getAttribute("x2"))).toBe(1252);
    }
    expect(Number(attr("waterline", "x2"))).toBe(1252);

    observer.resizeTo(480);
    expect(svg).toHaveAttribute("viewBox", "0 0 480 280");
    expect(coordinates(attr("return-curve", "d"))[2]![0]).toBeCloseTo(480 - 6, 1);
    expect(coordinates(attr("return-curve", "d"))[2]![1]).toBeCloseTo(TOP, 1);
  });

  it("keeps font sizes and strokes constant in pixels across widths", () => {
    const observer = stubResizeObserver();
    renderChart(CURVE);
    const before = [attr("return-curve", "stroke-width"), screen.getAllByTestId("y-label")[0]!.parentElement!.getAttribute("class")];
    observer.resizeTo(1600);
    const after = [attr("return-curve", "stroke-width"), screen.getAllByTestId("y-label")[0]!.parentElement!.getAttribute("class")];
    expect(after).toEqual(before);
    expect(attr("return-curve", "stroke-width")).toBe("2.2");
  });

  it("ignores an empty measurement (a hidden box) and keeps the last good width", () => {
    const observer = stubResizeObserver();
    renderChart(CURVE);
    observer.resizeTo(900);
    observer.resizeTo(0);
    expect(screen.getByRole("img")).toHaveAttribute("viewBox", "0 0 900 280");
  });

  it("never draws narrower than a readable minimum", () => {
    const observer = stubResizeObserver();
    renderChart(CURVE);
    observer.resizeTo(40);
    expect(screen.getByRole("img")).toHaveAttribute("viewBox", "0 0 280 280");
  });

  it("stops observing when it unmounts", () => {
    const observer = stubResizeObserver();
    const { unmount } = renderChart(CURVE);
    unmount();
    expect(observer.disconnect).toHaveBeenCalled();
  });
});

describe("ReturnChart marker", () => {
  const CURVE_JULY = [point("2026-07-01", 1, 0), point("2026-07-02", 1.1, 0), point("2026-07-04", 1.2, 0)];
  const MARK = { date: "2026-07-02", label: "You joined on Jul 2" };

  function renderMarked(marker: { date: string; label: string } | null | undefined, range: RangeName = "All") {
    return render(<ReturnChart curve={CURVE_JULY} range={range} asOf={AS_OF} {...(marker === undefined ? {} : { marker })} />);
  }

  it("draws a labelled vertical line on the marked day, inside the plot", () => {
    renderMarked(MARK);

    const line = screen.getByTestId("seat-marker");
    const x = Number(line.getAttribute("x1"));
    expect(x).toBeGreaterThan(LEFT);
    expect(x).toBeLessThan(RIGHT);
    expect(line.getAttribute("x2")).toBe(line.getAttribute("x1"));
    expect(screen.getByText(MARK.label)).toBeInTheDocument();
  });

  it("puts the line where that day sits on the axis", () => {
    renderMarked(MARK);
    // All runs 07-01 to 09-30 (91 days): the 2nd is one day in.
    expect(Number(attr("seat-marker", "x1"))).toBeCloseTo(LEFT + (RIGHT - LEFT) / 91, 1);
  });

  it("draws nothing for a day before the window or after today", () => {
    const { unmount } = renderMarked({ date: "2026-06-30", label: "early" });
    expect(screen.queryByTestId("seat-marker")).not.toBeInTheDocument();
    unmount();
    renderMarked({ date: "2026-10-01", label: "late" });
    expect(screen.queryByTestId("seat-marker")).not.toBeInTheDocument();
  });

  it("draws nothing for a day outside a bounded window", () => {
    // 7D ends 09-30: a seat that began in July is not in it.
    renderMarked(MARK, "7D");
    expect(screen.queryByTestId("seat-marker")).not.toBeInTheDocument();
  });

  it("draws no marker without one, and the curve is the same", () => {
    const { unmount } = renderMarked(undefined);
    expect(screen.queryByTestId("seat-marker")).not.toBeInTheDocument();
    const without = attr("return-curve", "d");
    unmount();
    renderMarked(MARK);
    expect(attr("return-curve", "d")).toBe(without);
  });
});

describe("the modern chart: smoothing, gradient, vertical grid", () => {
  const CURVE = [
    point("2026-07-01", 1, 0),
    point("2026-07-02", 1.1, 0),
    point("2026-07-03", 1.3, 0),
    point("2026-07-04", 1.2, -1 / 13),
  ];
  const READ_ON_LAST_DAY = Date.UTC(2026, 6, 4, 12);

  it("draws the return curve and the drawdown edge and fill as cubic curves", () => {
    renderChart(CURVE, "All", READ_ON_LAST_DAY);
    for (const id of ["return-curve", "drawdown-edge", "drawdown-fill"]) {
      expect(attr(id, "d")).toMatch(/C/);
    }
  });

  it("never draws the curve above its highest day or below its lowest", () => {
    renderChart(CURVE, "All", READ_ON_LAST_DAY);
    const d = attr("return-curve", "d");
    // Every number of the path, control points included, lies between the plot's top (30%, the peak) and the waterline.
    const ys = [...d.matchAll(/-?[\d.]+,(-?[\d.]+)/g)].map((m) => Number(m[1]));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(TOP - 0.01);
    expect(Math.max(...ys)).toBeLessThanOrEqual(WATER_Y + 0.01);
  });

  it("fills under the return curve with a gradient in the curve's own colour", () => {
    renderChart(CURVE, "All", READ_ON_LAST_DAY);
    const fill = screen.getByTestId("return-fill");
    const id = /^url\(#(.+)\)$/.exec(fill.getAttribute("fill") ?? "")?.[1];
    expect(id).toBeTruthy();
    const gradient = screen.getByRole("img").querySelector(`linearGradient[id="${id}"]`);
    expect(gradient).not.toBeNull();
    const stops = [...gradient!.querySelectorAll("stop")];
    expect(stops.length).toBeGreaterThanOrEqual(2);
    expect(gradient).toHaveClass("text-gain");
    for (const stop of stops) expect(stop.getAttribute("stop-color")).toBe("currentColor");
    // It fades: strongest at the curve's farthest point from the waterline, none at the waterline. It spans the
    // curve's own height, not the plot's, so a curve near 0% still shows it.
    const opacities = stops.map((stop) => Number(stop.getAttribute("stop-opacity")));
    expect(Math.max(...opacities)).toBeGreaterThan(0.1);
    expect(Math.min(...opacities)).toBe(0);
    const ys = coordinates(attr("return-curve", "d")).map(([, y]) => y);
    expect(Number(gradient!.getAttribute("y1"))).toBeCloseTo(Math.min(WATER_Y, ...ys), 1);
    expect(Number(gradient!.getAttribute("y2"))).toBeCloseTo(Math.max(WATER_Y, ...ys), 1);
    const waterStop = stops.find((stop) => Number(stop.getAttribute("stop-opacity")) === 0)!;
    const span = Math.max(WATER_Y, ...ys) - Math.min(WATER_Y, ...ys);
    expect(Number(waterStop.getAttribute("offset"))).toBeCloseTo((WATER_Y - Math.min(WATER_Y, ...ys)) / span, 3);
    // The fill is the curve closed down to the waterline.
    const shape = attr("return-fill", "d");
    const corners = coordinates(shape);
    expect(corners[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(corners[corners.length - 1]![1]).toBeCloseTo(WATER_Y, 1);
    expect(shape.trim().endsWith("Z")).toBe(true);
    // Between those two waterline corners it runs along the return curve itself.
    expect(corners.slice(1, -1)).toEqual(coordinates(attr("return-curve", "d")));
    expect(fill).toHaveClass("stroke-none");
  });

  it("starts the gradient at the waterline when the curve never rises above 0%", () => {
    renderChart(
      [point("2026-07-01", 1, 0), point("2026-07-02", 0.95, -0.05), point("2026-07-03", 0.9, -0.1)],
      "All",
      Date.UTC(2026, 6, 3, 12),
    );
    const id = /^url\(#(.+)\)$/.exec(attr("return-fill", "fill"))?.[1];
    const gradient = screen.getByRole("img").querySelector(`linearGradient[id="${id}"]`)!;
    const ys = coordinates(attr("return-curve", "d")).map(([, y]) => y);
    expect(Number(gradient.getAttribute("y1"))).toBeCloseTo(WATER_Y, 1);
    expect(Number(gradient.getAttribute("y2"))).toBeCloseTo(Math.max(...ys), 1);
    const waterStop = [...gradient.querySelectorAll("stop")].find((stop) => Number(stop.getAttribute("stop-opacity")) === 0)!;
    expect(Number(waterStop.getAttribute("offset"))).toBe(0);
  });

  it("gives each chart its own gradient id, so two on a page do not share one", () => {
    render(
      <>
        <ReturnChart curve={CURVE} range="All" asOf={READ_ON_LAST_DAY} />
        <ReturnChart curve={CURVE} range="All" asOf={READ_ON_LAST_DAY} />
      </>,
    );
    const [one, two] = screen.getAllByTestId("return-fill").map((n) => n.getAttribute("fill"));
    expect(one).toMatch(/^url\(#.+\)$/);
    expect(one).not.toBe(two);
    const ids = [...document.querySelectorAll("linearGradient")].map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("draws no fill when there is no curve", () => {
    renderChart([]);
    expect(screen.queryByTestId("return-fill")).toBeNull();
  });

  it("draws a vertical grid line under each date label, styled like the horizontal ones", () => {
    renderChart(CURVE, "All", READ_ON_LAST_DAY);
    const labelXs = screen.getAllByTestId("day-label").map((n) => Number(n.getAttribute("x")));
    expect(labelXs).toHaveLength(4);
    const lines = screen.getAllByTestId("vgridline");
    expect(lines.map((line) => Number(line.getAttribute("x1")))).toEqual(labelXs);
    for (const line of lines) {
      expect(line.getAttribute("x2")).toBe(line.getAttribute("x1"));
      expect(Number(line.getAttribute("y1"))).toBeCloseTo(TOP, 1);
      expect(Number(line.getAttribute("y2"))).toBeCloseTo(TOP + 244, 1);
      expect(line).toHaveClass("stroke-rule-soft");
    }
  });

  it("draws the vertical lines of month labels too", () => {
    renderChart([point("2026-07-01", 1, 0), point("2026-09-30", 1.2, 0)]);
    const monthXs = screen.getAllByTestId("month-label").map((n) => Number(n.getAttribute("x")));
    expect(monthXs.length).toBeGreaterThan(0);
    const lineXs = screen.getAllByTestId("vgridline").map((n) => Number(n.getAttribute("x1")));
    for (const monthX of monthXs) expect(lineXs).toContain(monthX);
  });
});

describe("the hover readout", () => {
  const CURVE = [
    point("2026-07-01", 1, 0),
    point("2026-07-02", 1.1, 0),
    point("2026-07-03", 1.3, 0),
    point("2026-07-04", 1.2, -1 / 13),
  ];
  const STEP = (RIGHT - LEFT) / 3;

  function stubBox(svg: Element, width: number) {
    svg.getBoundingClientRect = () => ({
      left: 10,
      top: 0,
      width,
      height: 280,
      right: 10 + width,
      bottom: 280,
      x: 10,
      y: 0,
      toJSON: () => ({}),
    });
  }

  /** Stubs the svg's box: `width` CSS pixels for the 796-unit drawing. */
  function renderHovered(width = 796) {
    renderChart(CURVE, "All", Date.UTC(2026, 6, 4, 12));
    const svg = screen.getByRole("img");
    stubBox(svg, width);
    return svg;
  }

  /** jsdom has no PointerEvent, so the event is a plain one that carries the pointer's `clientX`. */
  function pointer(svg: Element, type: "pointerMove" | "pointerDown", clientX: number) {
    const event = createEvent[type](svg);
    Object.defineProperty(event, "clientX", { value: clientX });
    fireEvent(svg, event);
  }

  /** The client x that lands on the drawing's unit `x`. */
  const clientFor = (x: number, width = 796) => 10 + (x * width) / 796;

  it("shows nothing until the pointer is over the plot", () => {
    renderHovered();
    expect(screen.queryByTestId("hover-guide")).toBeNull();
    expect(screen.queryByTestId("hover-dot")).toBeNull();
    expect(screen.queryByTestId("hover-label")).toBeNull();
  });

  it("marks the nearest day with a guide, a dot on the curve and its date and return", () => {
    const svg = renderHovered();
    pointer(svg, "pointerMove", clientFor(LEFT + 2 * STEP + 9));

    const guide = screen.getByTestId("hover-guide");
    expect(Number(guide.getAttribute("x1"))).toBeCloseTo(LEFT + 2 * STEP, 1);
    expect(Number(guide.getAttribute("x2"))).toBeCloseTo(LEFT + 2 * STEP, 1);
    expect(Number(guide.getAttribute("y1"))).toBeCloseTo(TOP, 1);
    expect(Number(guide.getAttribute("y2"))).toBeCloseTo(TOP + 244, 1);

    const dot = screen.getByTestId("hover-dot");
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo(LEFT + 2 * STEP, 1);
    // 07-03 is the 30% peak: the top of the plot.
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(TOP, 1);
    expect(dot).toHaveClass("fill-gain");

    expect(screen.getByTestId("hover-label")).toHaveTextContent("Jul 3 · +30%");
  });

  it("follows the pointer to another day", () => {
    const svg = renderHovered();
    pointer(svg, "pointerMove", clientFor(LEFT + 1 * STEP - 7));
    expect(screen.getByTestId("hover-label")).toHaveTextContent("Jul 2 · +10%");
    pointer(svg, "pointerMove", clientFor(RIGHT));
    expect(screen.getByTestId("hover-label")).toHaveTextContent("Jul 4 · +20%");
    expect(Number(screen.getByTestId("hover-guide").getAttribute("x1"))).toBeCloseTo(RIGHT, 1);
  });

  it("reads the position in drawing units when the box is narrower than the drawing", () => {
    const svg = renderHovered(398);
    pointer(svg, "pointerMove", clientFor(LEFT + 1 * STEP, 398));
    expect(screen.getByTestId("hover-label")).toHaveTextContent("Jul 2 · +10%");
  });

  it("goes away when the pointer leaves, and when it is in the label gutter", () => {
    const svg = renderHovered();
    pointer(svg, "pointerMove", clientFor(LEFT + STEP));
    expect(screen.getByTestId("hover-guide")).toBeInTheDocument();
    fireEvent.pointerLeave(svg);
    expect(screen.queryByTestId("hover-guide")).toBeNull();
    expect(screen.queryByTestId("hover-label")).toBeNull();

    pointer(svg, "pointerMove", clientFor(LEFT + STEP));
    pointer(svg, "pointerMove", clientFor(LEFT - 20));
    expect(screen.queryByTestId("hover-guide")).toBeNull();
  });

  it("answers a touch (pointer down) like a move", () => {
    const svg = renderHovered();
    pointer(svg, "pointerDown", clientFor(LEFT));
    expect(screen.getByTestId("hover-label")).toHaveTextContent("Jul 1 · 0%");
  });

  it("draws no readout over an empty chart", () => {
    renderChart([]);
    const svg = screen.getByRole("img");
    stubBox(svg, 796);
    pointer(svg, "pointerMove", 410);
    expect(screen.queryByTestId("hover-guide")).toBeNull();
  });

  it("keeps the readout's label inside the drawing near either edge", () => {
    const svg = renderHovered();
    pointer(svg, "pointerMove", clientFor(RIGHT));
    expect(screen.getByTestId("hover-label")).toHaveAttribute("text-anchor", "end");
    pointer(svg, "pointerMove", clientFor(LEFT));
    expect(screen.getByTestId("hover-label")).toHaveAttribute("text-anchor", "start");
  });
});
