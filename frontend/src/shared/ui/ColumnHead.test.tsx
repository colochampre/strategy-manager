import { fireEvent, render, screen } from "@testing-library/react";
import { Coins } from "lucide-react";
import { describe, expect, it } from "vitest";

import { ColumnHead } from "@/shared/ui/ColumnHead";

function tipOf(name: string): HTMLElement {
  fireEvent.mouseEnter(screen.getByRole("img", { name }).parentElement as HTMLElement);
  return screen.getByRole("tooltip");
}

describe("ColumnHead", () => {
  it("names the column with its icon and opens its tip below, lined up with the figure column's end (L.10)", () => {
    render(<ColumnHead icon={Coins} label="PnL USDT" />);

    const tip = tipOf("PnL USDT");
    expect(tip).toHaveTextContent(/^PnL USDT$/);
    expect(tip).toHaveClass("top-full", "right-0");
    expect(tip).not.toHaveClass("bottom-full");
  });

  it("lines a left-aligned column's tip up with its start (L.10)", () => {
    render(<ColumnHead icon={Coins} label="Pair" align="start" />);

    const tip = tipOf("Pair");
    expect(tip).toHaveClass("top-full", "left-0");
    expect(tip).not.toHaveClass("right-0");
  });

  it("says the column's note after its name (L.10)", () => {
    render(<ColumnHead icon={Coins} label="Margin granted USDT" hint="What the share took." />);

    expect(tipOf("Margin granted USDT")).toHaveTextContent("Margin granted USDT. What the share took.");
  });
});
