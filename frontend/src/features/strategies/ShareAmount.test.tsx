import { render, screen } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it } from "vitest";

import { ShareAmount } from "@/features/strategies/ShareAmount";
import type { ShareAmountView } from "@/features/strategies/ShareAmount";
import i18n from "@/shared/i18n";

// The line under the track is presentational: it takes strings the server served and writes them (design
// § C2). It reads no pool and multiplies nothing.

const KNOWN: ShareAmountView = {
  kind: "known",
  amount: "335.000000000000000000",
  currency: "USDT",
  staleAt: null,
};

function renderAmount(view: ShareAmountView) {
  return render(<ShareAmount view={view} trailing={<button type="button">About this amount</button>} />);
}

describe("ShareAmount", () => {
  it("a known amount reads 'Asks for about 335.00 USDT per operation' from the served string", () => {
    renderAmount(KNOWN);

    expect(screen.queryByText("Asks for about 335.00 USDT per operation")).toBeInTheDocument();
  });

  it.each([
    ["4.999999999999999999", "4.99"],
    ["500.499500000000000000", "500.49"],
    ["1000.000000000000000000", "1,000.00"],
    ["0.059999999999999999", "0.05"],
    ["12.3", "12.30"],
  ])("the amount %s is cut down as text to two decimals, never rounded up: %s", (amount, written) => {
    renderAmount({ ...KNOWN, amount });

    expect(screen.queryByText(`Asks for about ${written} USDT per operation`)).toBeInTheDocument();
  });

  it("a coin-margined pool uses its own decimals", () => {
    renderAmount({ ...KNOWN, amount: "0.123456789999999999", currency: "BTC" });

    expect(screen.queryByText("Asks for about 0.12345678 BTC per operation")).toBeInTheDocument();
  });

  it("the amount is written in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      renderAmount({ ...KNOWN, amount: "1234.569999999999999999" });

      expect(screen.queryByText("Pide alrededor de 1234,56 USDT por operación")).toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("a stale balance shows the same line and the time it was read, as HH:MM UTC", () => {
    renderAmount({ ...KNOWN, staleAt: "2026-10-09T14:03:12Z" });

    expect(screen.queryByText("Asks for about 335.00 USDT per operation")).toBeInTheDocument();
    expect(
      screen.queryByText("The pool's balance was last read at 14:03 UTC and may be out of date."),
    ).toBeInTheDocument();
  });

  it("a balance that is not stale shows no such line", () => {
    renderAmount(KNOWN);

    expect(screen.queryByText(/may be out of date/)).toBeNull();
  });

  it("no balance shows its sentence and no figure, never a zero", () => {
    renderAmount({ kind: "noBalance" });

    expect(
      screen.queryByText("The pool's balance has not been read yet, so the amount cannot be shown."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(screen.queryByText(/\d/)).toBeNull();
  });

  it("loading shows 'Calculating the amount…' and no figure", () => {
    renderAmount({ kind: "loading" });

    expect(screen.queryByText("Calculating the amount…")).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(screen.queryByText(/\d/)).toBeNull();
  });

  it("a failed read shows 'The amount could not be loaded.'", () => {
    renderAmount({ kind: "failed" });

    expect(screen.queryByText("The amount could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
  });

  it.each(["abc", "1E+3", "-5", "", "12,5"])("a served amount %j that is not a plain decimal is a failed read, never NaN", (amount) => {
    renderAmount({ ...KNOWN, amount });

    expect(screen.queryByText("The amount could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
  });

  it("no valid value shows an em dash where the figure would be", () => {
    renderAmount({ kind: "none" });

    expect(screen.queryByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
  });

  it.each<[string, ShareAmountView]>([
    ["a figure", KNOWN],
    ["the em dash", { kind: "none" }],
    ["no balance", { kind: "noBalance" }],
    ["a loading mark", { kind: "loading" }],
    ["a failed read", { kind: "failed" }],
  ])("the row, and so its button slot, is present with %s", (_name, view) => {
    renderAmount(view);

    expect(screen.queryByRole("button", { name: "About this amount" })).toBeInTheDocument();
  });

  it("the row is present without a button too", () => {
    const { container } = render(<ShareAmount view={{ kind: "none" }} />);

    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(screen.queryByText("—")).toBeInTheDocument();
  });

  it("no element carries a style attribute", () => {
    const { container } = renderAmount({ ...KNOWN, staleAt: "2026-10-09T14:03:12Z" });

    expect(container.querySelectorAll("[style]")).toHaveLength(0);
  });
});
