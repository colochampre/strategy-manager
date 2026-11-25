import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SecondLine, StatsRow, StatTile, StrategyHeaderCard } from "@/features/strategies/StrategyHeaderCard";

function card() {
  render(
    <StrategyHeaderCard about={<p data-testid="about">About this strategy</p>}>
      <StatsRow testId="row">
        <StatTile testId="one" label="Total PnL" position={0} info={<span data-testid="tip">i</span>}>
          <span data-testid="lead">+187.25</span>
          <SecondLine testId="second" className="text-gain">
            +5.2%
          </SecondLine>
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
    expect(row).toHaveClass("grid", "grid-cols-2", "md:grid-cols-4", "border-t", "border-rule", "-mx-4", "md:-mx-6");
  });

  it("draws a figure as a label over a large mono value, with a quiet second line under it", () => {
    const header = card();

    const one = within(header).getByTestId("one");
    expect(one.querySelector("dt")).toHaveTextContent(/^Total PnL/);
    expect(one.querySelector("dt")).toHaveClass("text-ink-3", "text-[12.5px]");
    expect(within(one).getByTestId("tip")).toBeInTheDocument();
    expect(one.querySelector("dd")).toHaveClass("font-mono", "text-xl", "font-medium");
    const second = within(one).getByTestId("second");
    expect(second).toHaveClass("block", "text-[12.5px]", "text-gain", "font-sans");
    expect(second).not.toHaveClass("text-ink-3");
    // The second line is one of the value's own children, after the lead.
    expect(Array.from((one.querySelector("dd") as HTMLElement).children).map((node) => node.getAttribute("data-testid"))).toEqual([
      "lead",
      "second",
    ]);
  });

  it("rules the figures apart as the dashboard's do: the last one has none", () => {
    const header = card();

    expect(within(header).getByTestId("one")).toHaveClass("border-r", "border-rule", "md:pl-6");
    expect(within(header).getByTestId("three")).toHaveClass("border-r", "border-rule");
    expect(within(header).getByTestId("four")).not.toHaveClass("border-r");
    expect(within(header).getByTestId("four")).not.toHaveClass("md:border-r");
  });
});
