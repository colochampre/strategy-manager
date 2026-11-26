import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HintedHead } from "@/shared/ui/HintedHead";

function tipOf(name: string): HTMLElement {
  fireEvent.mouseEnter(screen.getByText(name));
  return screen.getByRole("tooltip");
}

describe("HintedHead", () => {
  it("writes the column's name in words, with no tip when it has no note (L30)", () => {
    const { container } = render(<HintedHead label="PnL USDT" />);

    expect(container).toHaveTextContent(/^PnL USDT$/);
    fireEvent.mouseEnter(screen.getByText("PnL USDT"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("opens the column's note below, lined up with a figure column's end (L30)", () => {
    render(<HintedHead label="Margin granted USDT" hint="What the share took." />);

    const tip = tipOf("Margin granted USDT");
    expect(tip).toHaveTextContent(/^What the share took\.$/);
    expect(tip).toHaveClass("top-full", "right-0");
  });

  it("lines a left-aligned column's note up with its start (L30)", () => {
    render(<HintedHead label="Pair" hint="The venue's spelling." align="start" />);

    expect(tipOf("Pair")).toHaveClass("top-full", "left-0");
  });
});
