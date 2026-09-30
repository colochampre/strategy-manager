import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReturnChart } from "@/features/overview/ReturnChart";
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
    render(<ReturnChart curve={curve} />);

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
    render(<ReturnChart curve={[point("2026-07-01", 1, 0), point("2026-07-02", 1.05, -0.02)]} />);
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
    render(<ReturnChart curve={[point("2026-07-01", 1, 0), point("2026-07-02", 1.3, -0.02)]} />);
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
    render(<ReturnChart curve={curve} />);
    const ticks = screen.getAllByTestId("month-label");
    expect(ticks.map((node) => node.textContent)).toEqual(["Aug", "Sep"]);
    // 2026-08-01 is 18 of 58 days into the span.
    expect(Number(ticks[0]!.getAttribute("x"))).toBeCloseTo(LEFT + ((RIGHT - LEFT) * 18) / 58, 1);
  }

  it("drops month labels that would overprint the previous one on a long history", () => {
    // Four years in 746 units is about 15 units a month: labels need 28 to stay legible.
    render(<ReturnChart curve={[point("2023-01-01", 1, 0), point("2026-12-31", 1.5, 0)]} />);
    const xs = screen.getAllByTestId("month-label").map((n) => Number(n.getAttribute("x")));
    expect(xs.length).toBeGreaterThan(10);
    expect(xs.length).toBeLessThan(48);
    for (let i = 1; i < xs.length; i += 1) expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(28);
  });

  it("draws a negative cumulative return in the lower band, on the same scale as the drawdown", () => {
    const curve = [point("2026-07-01", 1, 0), point("2026-07-02", 0.75, -0.25)];
    render(<ReturnChart curve={curve} />);
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
    render(<ReturnChart curve={[point("2026-07-01", 1, 0), point("2026-07-02", 1, 0)]} />);
    const d = attr("return-curve", "d");
    expect(d).not.toMatch(/NaN|Infinity/);
    for (const [, y] of coordinates(d)) expect(y).toBeCloseTo(WATER_Y, 1);
  });

  it("draws a single day as a point at the centre", () => {
    render(<ReturnChart curve={[point("2026-07-01", 1.1, 0)]} />);
    const dot = screen.getByTestId("return-dot");
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo((LEFT + RIGHT) / 2, 1);
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(WATER_Y - UPPER, 1);
    expect(dot).toHaveClass("fill-gain");
    expect(attr("return-curve", "d")).not.toMatch(/NaN/);
  });

  it("test_empty_state_no_closed_trades_yet_when_curve_is_empty", () => {
    render(<ReturnChart curve={[]} />);
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

  it("test_chart_always_shows_all_range_selector_does_not_rebase_axis", () => {
    // 90 days with the peak and the deepest drawdown in the FIRST month, then flat.
    const curve = Array.from({ length: 90 }, (_, i) =>
      i === 5
        ? point(day(i), 1.4, 0)
        : i === 8
          ? point(day(i), 1.2, -0.14)
          : point(day(i), i < 5 ? 1 + i * 0.08 : 1.2, i < 8 ? 0 : -0.1),
    );
    render(<ReturnChart curve={curve} />);

    const line = coordinates(attr("return-curve", "d"));
    // Every day is drawn, from the first to the last, not just the latest 7, 30 or 90.
    expect(line).toHaveLength(90);
    expect(line[0]![0]).toBeCloseTo(LEFT, 1);
    expect(line[89]![0]).toBeCloseTo(RIGHT, 1);
    // The axis still reaches the early 40% peak, which a 30-day window would have dropped.
    expect(Math.min(...line.map(([, y]) => y))).toBeCloseTo(TOP, 1);
    expect(screen.getAllByTestId("y-label").map((n) => n.textContent)).toContain("+40%");
    // There is no range control in the chart: the selector drives the ledger line only.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(within(screen.getByRole("figure")).queryByText(/30D|7D|90D|1Y/)).toBeNull();
    // All 3 months are labelled, the first one included.
    expect(screen.getAllByTestId("month-label").map((n) => n.textContent)).toEqual(["Jul", "Aug", "Sep"]);
  });

  it("test_role_img_aria_label_from_i18n", async () => {
    render(<ReturnChart curve={[point("2026-07-01", 1, 0), point("2026-07-02", 1.1, 0)]} />);
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
    render(<ReturnChart curve={[]} />);
    const svg = screen.getByRole("img");
    expect(svg).toHaveAttribute("viewBox", "0 0 796 330");
    expect(svg).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
    expect(svg).toHaveClass("w-full", "h-auto");
    expect(svg).not.toHaveAttribute("width");
  });

  it("refuses to draw an unreadable curve instead of a silent wrong line", () => {
    const broken = [point("2026-07-01", 1, 0), { ...point("2026-07-02", 1.1, 0), index: "abc" }];
    render(<ReturnChart curve={broken} />);
    expect(screen.getByRole("alert")).toHaveTextContent(en.overview.returnChart.unreadable);
    expect(screen.queryByTestId("return-curve")).toBeNull();
  });

  it("has a translated title and caption in both languages", () => {
    render(<ReturnChart curve={[]} />);
    expect(screen.getByRole("heading", { name: en.overview.returnChart.title })).toBeInTheDocument();
    expect(screen.getByText(en.overview.returnChart.caption)).toBeInTheDocument();
    expect(Object.keys(es.overview.returnChart).sort()).toEqual(Object.keys(en.overview.returnChart).sort());
  });
});
