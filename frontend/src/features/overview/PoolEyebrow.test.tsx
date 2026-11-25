import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PoolEyebrow } from "@/features/overview/PoolEyebrow";
import i18n from "@/shared/i18n";

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("PoolEyebrow", () => {
  it("names the exchange by its display name, then the venue and the currency (ex1 .hc-sub)", () => {
    render(<PoolEyebrow exchange="bybit" venue="linear" currency="USDT" />);
    const eyebrow = screen.getByTestId("pool-eyebrow");
    // The exchange is its display name (7p.1, owner decision 77); the venue stays its identifier.
    expect(eyebrow.textContent).toBe("Bybit, linear pool in USDT");
    expect(eyebrow).toHaveClass("text-[13px]", "text-ink-3");
  });

  it("says a sole pool is single and leaves the venue out", () => {
    render(<PoolEyebrow exchange="binance" venue="usdt-m" currency="USDT" sole />);

    expect(screen.getByTestId("pool-eyebrow").textContent).toBe("Binance, single USDT pool");
  });

  it("writes it in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(
      <>
        <PoolEyebrow exchange="binance" venue="usdt-m" currency="USDT" sole />
        <PoolEyebrow exchange="bybit" venue="spot" currency="USDT" />
      </>,
    );

    expect(screen.getAllByTestId("pool-eyebrow").map((node) => node.textContent)).toEqual([
      "Binance, pool único en USDT",
      "Bybit, pool spot en USDT",
    ]);
  });

  it("keeps two pools of one exchange apart", () => {
    render(
      <>
        <PoolEyebrow exchange="pionex" venue="spot" currency="USDT" />
        <PoolEyebrow exchange="pionex" venue="usdt-m" currency="USDT" />
      </>,
    );
    const eyebrows = screen.getAllByTestId("pool-eyebrow").map((node) => node.textContent);
    expect(eyebrows).toEqual(["Pionex, spot pool in USDT", "Pionex, usdt-m pool in USDT"]);
  });

  it("capitalises an exchange that has no display name", () => {
    render(<PoolEyebrow exchange="kraken" venue="spot" currency="USDT" />);

    expect(screen.getByTestId("pool-eyebrow").textContent).toBe("Kraken, spot pool in USDT");
  });
});
