import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatsRow, StatTile, StrategyHeaderCard } from "@/features/strategies/StrategyHeaderCard";

function card() {
  render(
    <StrategyHeaderCard about={<p data-testid="about">About this strategy</p>}>
      <StatsRow testId="row">
        <StatTile testId="one" label="Total PnL" position={0} info={<span data-testid="tip">i</span>}>
          <span data-testid="lead">+187.25</span>
          <span data-testid="beside">USDT</span>
        </StatTile>
        <StatTile testId="two" label="Max drawdown" position={1}>
          -4.8%
        </StatTile>
        <StatTile testId="three" label="Win rate" position={2}>
          61%
        </StatTile>
        <StatTile testId="four" label="AuM" position={3}>
          4,200.00
        </StatTile>
      </StatsRow>
    </StrategyHeaderCard>,
  );
  return screen.getByTestId("strategy-header-card");
}

describe("the strategy header card (S14, as ex1's header card)", () => {
  it("is the dashboard card's frame: a panel with a rule, the description first and the figure row under it", () => {
    const header = card();

    expect(header.tagName).toBe("SECTION");
    expect(header).toHaveClass("rounded-[10px]", "border", "border-rule", "bg-panel");
    expect(
      within(header).getByTestId("about").compareDocumentPosition(within(header).getByTestId("row")) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("draws the row as the dashboard does: four columns from md, a rule over it, edge to edge of the card", () => {
    const row = within(card()).getByTestId("row");

    expect(row.tagName).toBe("DL");
    expect(row).toHaveClass("grid", "grid-cols-2", "border-t", "border-rule", "-mx-4", "md:-mx-6");
    // Each column as wide as its figure needs, the room left shared out: a long AuM takes it from a short return (L42).
    expect(row).toHaveClass("md:grid-cols-[repeat(4,auto)]");
    for (const id of ["one", "two", "three", "four"]) {
      const tile = within(row).getByTestId(id);
      // From md no column narrows below its value, and a label asks only for its longest word, then fills the column.
      expect(tile).toHaveClass("min-w-0", "md:min-w-auto");
      expect(tile.querySelector("dt")).toHaveClass("w-min", "min-w-full");
    }
  });

  it("draws a figure as a label over a large mono value, its quiet part on the same line while it fits", () => {
    const header = card();

    const one = within(header).getByTestId("one");
    expect(one.querySelector("dt")).toHaveTextContent(/^Total PnL/);
    expect(one.querySelector("dt")).toHaveClass("text-ink-3", "text-[12.5px]");
    expect(within(one).getByTestId("tip")).toBeInTheDocument();
    // 18 px, so five figures fit one row (L42).
    expect(one.querySelector("dd")).toHaveClass("font-mono", "text-lg", "font-medium");
    expect(one.querySelector("dd")).not.toHaveClass("text-xl");
    // One line, and the quiet part goes under the lead only where the column cannot hold both (L42).
    expect(one.querySelector("dd")).toHaveClass("flex", "flex-wrap", "items-baseline");
    expect(Array.from((one.querySelector("dd") as HTMLElement).children).map((node) => node.getAttribute("data-testid"))).toEqual([
      "lead",
      "beside",
    ]);
  });

  it("sets every value at the foot of its figure, so a label on two lines does not lower one value alone (L42)", () => {
    const header = card();

    for (const id of ["one", "two", "three", "four"]) {
      const tile = within(header).getByTestId(id);
      expect(tile).toHaveClass("flex", "flex-col");
      expect(tile.querySelector("dd")).toHaveClass("mt-auto");
    }
  });

  it("rules five figures apart: one row from md, the fifth alone on a phone's last row (L42)", () => {
    render(
      <StatsRow testId="five-row" count={5}>
        {["a", "b", "c", "d", "e"].map((id, position) => (
          <StatTile key={id} testId={`five-${id}`} label={id} position={position} count={5}>
            1
          </StatTile>
        ))}
      </StatsRow>,
    );

    expect(screen.getByTestId("five-row")).toHaveClass("md:grid-cols-[repeat(5,auto)]");
    // A rule after each of the first four on md: the even ones carry theirs at every size.
    for (const id of ["a", "c"]) expect(screen.getByTestId(`five-${id}`)).toHaveClass("border-r");
    for (const id of ["b", "d"]) expect(screen.getByTestId(`five-${id}`)).toHaveClass("md:border-r");
    expect(screen.getByTestId("five-a")).toHaveClass("md:pl-6", "border-r", "border-b");
    expect(screen.getByTestId("five-c")).toHaveClass("border-r", "border-b");
    expect(screen.getByTestId("five-e")).toHaveClass("col-span-2", "md:col-span-1");
    expect(screen.getByTestId("five-e")).not.toHaveClass("border-r");
    expect(screen.getByTestId("five-e")).not.toHaveClass("md:border-r");
    expect(screen.getByTestId("five-e")).not.toHaveClass("border-b");
  });

  it("rules the figures apart as the dashboard's do: the last one has none", () => {
    const header = card();

    expect(within(header).getByTestId("one")).toHaveClass("border-r", "border-rule", "md:pl-6");
    expect(within(header).getByTestId("three")).toHaveClass("border-r", "border-rule");
    expect(within(header).getByTestId("four")).not.toHaveClass("border-r");
    expect(within(header).getByTestId("four")).not.toHaveClass("md:border-r");
  });
});
