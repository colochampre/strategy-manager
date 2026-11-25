import { act, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ReturnChart } from "@/features/overview/ReturnChart";
import type { CurvePoint } from "@/shared/api/types";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import i18n from "@/shared/i18n";

/** S1, L15, ex2: while the balances are hidden every chart hides its axes and what its tooltip would say. */

const AS_OF = Date.UTC(2026, 6, 4, 12);
const point = (date: string, index: number, drawdown: number): CurvePoint => ({
  date,
  daily_return: "0",
  index: String(index),
  drawdown: String(drawdown),
});
const CURVE = [
  point("2026-07-01", 1, 0),
  point("2026-07-02", 1.1, 0),
  point("2026-07-03", 1.3, 0),
  point("2026-07-04", 1.2, -1 / 13),
];

beforeEach(() => {
  window.localStorage.clear();
  useHiddenStore.setState({ hidden: true });
});
afterEach(async () => {
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});

function hover() {
  const svg = screen.getByRole("img");
  svg.getBoundingClientRect = () => ({ left: 10, top: 0, width: 796, height: 280, right: 806, bottom: 280, x: 10, y: 0, toJSON: () => ({}) });
  const event = createEvent.pointerMove(svg);
  Object.defineProperty(event, "clientX", { value: 10 + 400 });
  fireEvent(svg, event);
}

describe("the return chart while the balances are hidden", () => {
  it("draws no axis label, on either axis, and keeps the curve and its gridlines", () => {
    render(<ReturnChart curve={CURVE} range="All" asOf={AS_OF} />);

    expect(screen.queryAllByTestId("y-label")).toHaveLength(0);
    expect(screen.queryAllByTestId("month-label")).toHaveLength(0);
    expect(screen.queryAllByTestId("day-label")).toHaveLength(0);
    expect(screen.getByTestId("return-curve")).toBeInTheDocument();
    expect(screen.getByTestId("waterline")).toBeInTheDocument();
    expect(screen.getAllByTestId("gridline").length).toBeGreaterThan(0);
  });

  it("draws the plot from the left edge, where the axis labels were", () => {
    render(<ReturnChart curve={CURVE} range="All" asOf={AS_OF} />);

    expect(Number(screen.getByTestId("waterline").getAttribute("x1"))).toBeLessThan(44);
  });

  it("marks the hovered day with its guide and dot, and writes no value", () => {
    render(<ReturnChart curve={CURVE} range="All" asOf={AS_OF} />);
    hover();

    expect(screen.getByTestId("hover-guide")).toBeInTheDocument();
    expect(screen.getByTestId("hover-dot")).toBeInTheDocument();
    expect(screen.queryByTestId("hover-label")).toBeNull();
    expect(screen.queryByTestId("hover-drawdown")).toBeNull();
  });

  it("draws the axes and the tooltip again once the balances are shown", () => {
    useHiddenStore.setState({ hidden: false });
    render(<ReturnChart curve={CURVE} range="All" asOf={AS_OF} />);
    hover();

    expect(screen.getAllByTestId("y-label").length).toBeGreaterThan(0);
    expect(screen.getByTestId("hover-label")).toBeInTheDocument();
    expect(Number(screen.getByTestId("waterline").getAttribute("x1"))).toBe(44);
  });
});
