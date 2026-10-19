import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PoolEyebrow } from "@/features/overview/PoolEyebrow";

describe("PoolEyebrow", () => {
  it("shows the exchange's display name, the venue and the currency, upper-cased by style only", () => {
    render(<PoolEyebrow exchange="bybit" venue="linear" currency="USDT" />);
    const eyebrow = screen.getByTestId("pool-eyebrow");
    // The exchange is its display name (7p.1, owner decision 77); the venue stays its identifier. CSS upper-cases it.
    expect(eyebrow.textContent).toBe("Bybit · linear · USDT");
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
    expect(eyebrows).toEqual(["Pionex · spot · USDT", "Pionex · usdt-m · USDT"]);
  });

  it("capitalises an exchange that has no display name", () => {
    render(<PoolEyebrow exchange="kraken" venue="spot" currency="USDT" />);

    expect(screen.getByTestId("pool-eyebrow").textContent).toBe("Kraken · spot · USDT");
  });
});
