import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReturnChart } from "@/features/overview/ReturnChart";
import type { RangeName } from "@/features/overview/RangeSelector";
import type { CurvePoint } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/**
 * The plot: x runs 44 to 790, the zero line sits at 16 + 0.62 * 288 = 194.56,
 * the top of the upper band is y 16 and the bottom of the lower band is y 304.
 */
const LEFT = 44;
const RIGHT = 790;
const TOP = 16;
const WATER_Y = 194.56;
const UPPER = 178.56;
const LOWER = 109.44;

function day(offset: number, base = Date.UTC(2026, 6, 1)): string {
  return new Date(base + offset * 86_400_000).toISOString().slice(0, 10);
}

function point(date: string, index: number, drawdown: number): CurvePoint {
  return { date, daily_return: "0", index: String(index), drawdown: String(drawdown) };
}

/** Parses `M x,y L x,y ...` into coordinates. */
function coordinates(d: string): Array<[number, number]> {
  return [...d.matchAll(/[ML]\s*(-?[\d.]+),(-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
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
    renderChart(curve);

    const line = coordinates(attr("return-curve", "d"));
    expect(line).toHaveLength(4);
    expect(line[0]![0]).toBeCloseTo(LEFT, 1);
    expect(line[3]![0]).toBeCloseTo(RIGHT, 1);
    // Upper extreme 30% is the top of the plot; 0 is the waterline; 10% a third of the way.
    expect(line[0]![1]).toBeCloseTo(WATER_Y, 1);
    expect(line[1]![1]).toBeCloseTo(WATER_Y - UPPER / 3, 1);
    expect(line[2]![1]).toBeCloseTo(TOP, 1);
    expect(line[3]![1]).toBeCloseTo(WATER_Y - (UPPER * 2) / 3, 1);
    // No smoothing: straight segments only.
    expect(attr("return-curve", "d")).not.toMatch(/[CQSTA]/);

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
        // `none` is a keyword, not a colour; nothing may carry a colour attribute.
        expect(element.getAttribute(name) ?? "none").toMatch(/^none$/);
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
    const curve = [
      point("2026-07-14", 1, 0),
      point("2026-08-20", 1.05, 0),
      point("2026-09-10", 1.1, 0),
    ];
    renderChart(curve);
    const ticks = screen.getAllByTestId("month-label");
    expect(ticks.map((node) => node.textContent)).toEqual(["Aug", "Sep"]);
    // 2026-08-01 is 18 of 58 days into the span.
    expect(Number(ticks[0]!.getAttribute("x"))).toBeCloseTo(LEFT + ((RIGHT - LEFT) * 18) / 58, 1);
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
    renderChart([point("2026-07-01", 1.1, 0)]);
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
    renderChart(curve, "All");

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
    expect(screen.getAllByTestId("month-label").map((n) => n.textContent)).toEqual(["Jul", "Aug", "Sep"]);
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

  it("scales the drawing with its box through a viewBox, without measuring", () => {
    renderChart([]);
    const svg = screen.getByRole("img");
    expect(svg).toHaveAttribute("viewBox", "0 0 796 330");
    expect(svg).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
    expect(svg).toHaveClass("w-full", "h-auto");
    expect(svg).not.toHaveAttribute("width");
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

  it("keeps the month labels of the whole series for All", () => {
    renderChart(RANGE_CURVE, "All");
    expect(labels("month-label")).toEqual(["Aug", "Sep"]);
    expect(labels("day-label")).toEqual([]);
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
