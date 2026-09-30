import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PoolEyebrow } from "@/features/overview/PoolEyebrow";

describe("PoolEyebrow", () => {
  it("shows the exchange, venue and currency identifiers, upper-cased by style only", () => {
    render(<PoolEyebrow exchange="bybit" venue="linear" currency="USDT" />);
    const eyebrow = screen.getByTestId("pool-eyebrow");
    // The text is the raw identifier (display names are owner polish 7p.1); CSS upper-cases it.
    expect(eyebrow).toHaveTextContent("bybit · linear · USDT");
    expect(eyebrow).toHaveClass("uppercase", "font-mono", "text-[11px]", "text-ink-3");
    expect(eyebrow).toHaveClass("tracking-[0.14em]");
  });

  it("keeps two pools of one exchange apart", () => {
    render(
      <>
        <PoolEyebrow exchange="pionex" venue="spot" currency="USDT" />
        <PoolEyebrow exchange="pionex" venue="usdt-m" currency="USDT" />
      </>,
    );
    const eyebrows = screen.getAllByTestId("pool-eyebrow").map((node) => node.textContent);
    expect(eyebrows).toEqual(["pionex · spot · USDT", "pionex · usdt-m · USDT"]);
  });
});
