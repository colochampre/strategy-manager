import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExchangeWordmark } from "@/shared/exchanges/ExchangeWordmark";

describe("ExchangeWordmark (owner decision 77)", () => {
  it.each([
    ["binance", "Binance"],
    ["bybit", "Bybit"],
    ["pionex", "Pionex"],
  ])("draws %s's logotype as one image named %s, with no text of its own", (exchange, name) => {
    const { container } = render(<ExchangeWordmark exchange={exchange} />);

    const image = screen.getByRole("img", { name });
    expect([image.tagName.toLowerCase(), container.textContent]).toEqual(["svg", ""]);
  });

  it("writes the capitalised name of an exchange with no logotype, and draws no image (Q2)", () => {
    const { container } = render(<ExchangeWordmark exchange="kraken" />);

    expect([container.textContent, screen.queryAllByRole("img")]).toEqual(["Kraken", []]);
  });

  it.each([
    ["binance", ["fill-brand-binance"]],
    ["bybit", ["fill-brand-bybit", "fill-ink"]],
    ["pionex", ["fill-brand-pionex"]],
  ])("colours %s through the palette's tokens, never a raw colour", (exchange, fills) => {
    const { container } = render(<ExchangeWordmark exchange={exchange} />);

    const svg = container.querySelector("svg");
    const used = [...(svg?.querySelectorAll("[class]") ?? [])]
      .flatMap((node) => (node.getAttribute("class") ?? "").split(" "))
      .filter((name) => name.startsWith("fill-"));
    expect([[...new Set(used)], svg?.querySelectorAll("[fill], [style]").length]).toEqual([fills, 0]);
  });

  it("passes its class to the image, so a caller sets the height", () => {
    render(<ExchangeWordmark exchange="binance" className="h-4" />);

    expect(screen.getByRole("img", { name: "Binance" })).toHaveClass("h-4");
  });
});
