import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LedgerLine } from "@/features/overview/LedgerLine";
import i18n from "@/shared/i18n";

const BASE = {
  currency: "USDT",
  available: "1284.520000000000000000",
  range: "30D" as const,
  pnl: "41.2000000000",
  ret: "0.0340000000" as string | null,
  maxDrawdown: "-0.0200000000",
};

function text(): string {
  return (screen.getByTestId("ledger-line").textContent ?? "").replace(/\s+/g, " ").trim();
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("LedgerLine", () => {
  it("test_lead_figure_is_available_balance_pnl_and_return_by_sign_null_return_renders_em_dash", () => {
    const { rerender } = render(<LedgerLine {...BASE} />);
    expect(text()).toBe("1,284.52 USDT available · PnL 30D +41.20 · return 30D +3.4% · deepest -2.0%");

    // The lead figure is the available balance, large and in the primary ink.
    const lead = screen.getByTestId("ledger-lead");
    expect(lead).toHaveTextContent("1,284.52");
    expect(lead).toHaveClass("text-ink", "text-[26px]", "font-semibold");

    // PnL and return take their colour from their sign, at weight 600.
    expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-gain", "font-semibold");
    expect(screen.getByTestId("ledger-return")).toHaveClass("text-gain", "font-semibold");
    // The deepest drawdown is the all-time figure, always a loss.
    expect(screen.getByTestId("ledger-deepest")).toHaveClass("text-loss", "font-semibold");

    rerender(<LedgerLine {...BASE} pnl="-41.2000000000" ret="-0.0340000000" />);
    expect(text()).toBe("1,284.52 USDT available · PnL 30D -41.20 · return 30D -3.4% · deepest -2.0%");
    expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-loss");
    expect(screen.getByTestId("ledger-return")).toHaveClass("text-loss");

    // A null return is an em dash, never a zero, and it carries no sign colour.
    rerender(<LedgerLine {...BASE} ret={null} />);
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^—$/);
    expect(text()).toContain("return 30D —");
    expect(text()).not.toContain("return 30D 0");
    expect(text()).not.toContain("return 30D +0");
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-gain");
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-loss");
  });

  it("shows a return of exactly zero as 0.0%, a real figure, unlike the em dash", () => {
    render(<LedgerLine {...BASE} ret="0.0000000000" />);
    expect(screen.getByTestId("ledger-return")).toHaveTextContent("0.0%");
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-gain");
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-loss");
  });

  it("shows an em dash for an available balance nothing has synced", () => {
    render(<LedgerLine {...BASE} available={null} />);
    expect(screen.getByTestId("ledger-lead")).toHaveTextContent(/^—$/);
    expect(text()).toContain("USDT available");
  });

  it("names the range in PnL and return, and never pairs them with another range's label", () => {
    render(<LedgerLine {...BASE} range="All" />);
    expect(text()).toContain("PnL All ");
    expect(text()).toContain("return All ");
  });

  it("formats each pool's figures in its own settlement currency and never combines two pools", () => {
    render(
      <>
        <LedgerLine {...BASE} />
        <LedgerLine {...BASE} currency="BTC" available="0.123456789000" pnl="0.00012340" />
      </>,
    );
    const lines = screen.getAllByTestId("ledger-line");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveTextContent("1,284.52 USDT available");
    // A BTC pool keeps its eight decimals; USDT's two would erase a BTC-sized PnL.
    expect(lines[1]).toHaveTextContent("0.12345679 BTC available");
    expect(lines[1]).toHaveTextContent("+0.00012340");
    // Nothing on the page is a total across the two.
    expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("1,284.64");
  });

  it("formats numbers for the active language", async () => {
    await act(() => i18n.changeLanguage("es"));
    // Spanish groups thousands from five digits, not four: the locale decides, not this code.
    render(<LedgerLine {...BASE} available="12845.520000000000000000" />);
    expect(screen.getByTestId("ledger-lead")).toHaveTextContent("12.845,52");
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+41,20");
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^\+3,4\s%$/u);
  });

  it("reads every word in the active language", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(<LedgerLine {...BASE} range="1Y" available="12845.520000000000000000" />);
    expect(text()).toBe(
      "12.845,52 USDT disponibles · PnL 1A +41,20 · rendimiento 1A +3,4 % · caída máxima -2,0 %",
    );
  });

  it("shows an alert rather than NaN when a figure cannot be read", () => {
    const { container, rerender } = render(<LedgerLine {...BASE} pnl="abc" />);
    expect(screen.getByRole("alert")).toHaveTextContent("The figures could not be read.");
    expect(container).not.toHaveTextContent("NaN");

    rerender(<LedgerLine {...BASE} ret="1e-3" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<LedgerLine {...BASE} available="" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<LedgerLine {...BASE} maxDrawdown="-" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
