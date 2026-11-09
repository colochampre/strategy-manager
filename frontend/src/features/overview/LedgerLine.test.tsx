import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
  const values = Array.from(screen.getByTestId("ledger-line").querySelectorAll("dd"));
  return values.map((value) => (value.textContent ?? "").replace(/\s+/g, " ").trim()).join(" ");
}

/** The icon that names a figure: it is in the figure's term, the one before the value. */
function termOf(testId: string): HTMLElement {
  return screen.getByTestId(testId).previousElementSibling as HTMLElement;
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("LedgerLine", () => {
  it("test_lead_figure_is_available_balance_pnl_and_return_by_sign_null_return_renders_em_dash", () => {
    const { rerender } = render(<LedgerLine {...BASE} />);
    // Only the values are written: the words live in the icons' tooltips.
    expect(text()).toBe("1,284.52 USDT +41.20 +3.4% -2.0%");

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
    expect(text()).toBe("1,284.52 USDT -41.20 -3.4% -2.0%");
    expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-loss");
    expect(screen.getByTestId("ledger-return")).toHaveClass("text-loss");

    // A null return is an em dash, never a zero, and it carries no sign colour.
    rerender(<LedgerLine {...BASE} ret={null} />);
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^—$/);
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
  });

  it("names each figure with the card's icon, and says the words in its tooltip", () => {
    render(<LedgerLine {...BASE} />);

    for (const [testId, icon, name] of [
      ["ledger-lead", "wallet", "Available balance"],
      ["ledger-pnl", "coins", "PnL 30D"],
      ["ledger-return", "trending-up", "Return 30D"],
      ["ledger-deepest", "trending-down", "Deepest drawdown"],
    ] as const) {
      const term = termOf(testId);
      expect(term.querySelector(`svg.lucide-${icon}`), testId).not.toBeNull();
      expect(term.textContent, testId).toBe("");
      expect(within(term).getByRole("img", { name }), testId).toBeInTheDocument();
    }
    fireEvent.mouseEnter(within(termOf("ledger-deepest")).getByRole("img").parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Deepest drawdown");
  });

  it("names the range in the PnL and return tooltips only when it is not All", () => {
    const { rerender } = render(<LedgerLine {...BASE} range="All" />);
    expect(within(termOf("ledger-pnl")).getByRole("img", { name: "PnL" })).toBeInTheDocument();
    expect(within(termOf("ledger-return")).getByRole("img", { name: "Return" })).toBeInTheDocument();

    rerender(<LedgerLine {...BASE} range="7D" />);
    expect(within(termOf("ledger-pnl")).getByRole("img", { name: "PnL 7D" })).toBeInTheDocument();
    expect(within(termOf("ledger-return")).getByRole("img", { name: "Return 7D" })).toBeInTheDocument();
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
    expect(lines[0]).toHaveTextContent("1,284.52 USDT");
    // A BTC pool keeps its eight decimals; USDT's two would erase a BTC-sized PnL.
    expect(lines[1]).toHaveTextContent("0.12345679 BTC");
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
    expect(text()).toBe("12.845,52 USDT +41,20 +3,4 % -2,0 %");
    expect(within(termOf("ledger-lead")).getByRole("img", { name: "Saldo disponible" })).toBeInTheDocument();
    expect(within(termOf("ledger-pnl")).getByRole("img", { name: "PnL 1A" })).toBeInTheDocument();
    expect(within(termOf("ledger-return")).getByRole("img", { name: "Rendimiento 1A" })).toBeInTheDocument();
    expect(within(termOf("ledger-deepest")).getByRole("img", { name: "Caída máxima" })).toBeInTheDocument();
  });

  it("keeps each value on one line, so a currency never strands from its number", () => {
    render(<LedgerLine {...BASE} currency="BTC" available="0.12345678" pnl="0.00012340" />);
    const values = screen.getByTestId("ledger-line").querySelectorAll("dd");
    expect(values).toHaveLength(4);
    for (const value of values) expect(value).toHaveClass("whitespace-nowrap");
    expect(screen.getByTestId("ledger-line").className).not.toMatch(/whitespace-nowrap/);
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

  describe("without an available balance (one strategy's line)", () => {
    const { available: _omitted, ...WITHOUT_BALANCE } = BASE;

    it("leads with the PnL and has no balance figure", () => {
      render(<LedgerLine {...WITHOUT_BALANCE} />);

      expect(text()).toBe("+41.20 +3.4% -2.0%");
      expect(screen.queryByTestId("ledger-lead")).toBeNull();
      expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-[26px]", "font-semibold", "text-gain");
    });

    it("gives the lead figure the sign colour of a loss", () => {
      render(<LedgerLine {...WITHOUT_BALANCE} pnl="-41.2000000000" />);

      expect(text()).toBe("-41.20 +3.4% -2.0%");
      expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-loss", "text-[26px]");
    });

    it("still renders a null return as an em dash and an unreadable figure as an alert", () => {
      const { rerender } = render(<LedgerLine {...WITHOUT_BALANCE} ret={null} />);
      expect(text()).toBe("+41.20 — -2.0%");

      rerender(<LedgerLine {...WITHOUT_BALANCE} pnl="1e3" />);
      expect(screen.getByRole("alert")).toHaveTextContent("The figures could not be read.");
    });

    it("uses the return label it is given in place of the pool's", () => {
      render(<LedgerLine {...WITHOUT_BALANCE} returnLabel="Contribution to the pool 30D" />);

      expect(within(termOf("ledger-return")).getByRole("img", { name: "Contribution to the pool 30D" })).toBeInTheDocument();
    });
  });
});
