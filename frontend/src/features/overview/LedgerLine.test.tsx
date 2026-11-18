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

/** The groups of the line, in order: each one's test id. */
function groups(): string[] {
  return Array.from(screen.getByTestId("ledger-line").children).map((child) => child.getAttribute("data-testid") ?? "");
}

/** A group's term: its icon and its title. */
function term(group: string): HTMLElement {
  return within(screen.getByTestId(group)).getByRole("term");
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("LedgerLine", () => {
  it("draws the strategy pages' groups, an icon and a title over each group's values (owner, 2026-11-17)", () => {
    render(<LedgerLine {...BASE} />);

    expect(groups()).toEqual(["ledger-group-available", "ledger-group-pnl", "ledger-group-drawdown"]);
    for (const [group, icon, title] of [
      ["ledger-group-available", "wallet", "Available balance"],
      ["ledger-group-pnl", "coins", "Total PnL · 30D"],
      ["ledger-group-drawdown", "trending-down", "Max drawdown"],
    ] as const) {
      expect(term(group).querySelector(`svg.lucide-${icon}`), group).not.toBeNull();
      expect(term(group), group).toHaveTextContent(title);
    }
    // The line is the cards' grid.
    expect(screen.getByTestId("ledger-line")).toHaveClass("grid", "lg:auto-cols-fr");
  });

  it("writes each value with its unit joined and smaller, the PnL and return together, in their signs' colours", () => {
    const { rerender } = render(<LedgerLine {...BASE} />);

    expect(screen.getByTestId("ledger-lead")).toHaveTextContent(/^1,284\.52USDT$/);
    expect(screen.getByTestId("ledger-lead").lastElementChild).toHaveClass("text-[0.75em]");
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent(/^\+41\.20USDT$/);
    expect(screen.getByTestId("ledger-pnl")).toHaveClass("text-gain");
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^\+3\.4%$/);
    expect(screen.getByTestId("ledger-return")).toHaveClass("text-gain");
    expect(within(screen.getByTestId("ledger-group-pnl")).getByTestId("ledger-return")).toBeInTheDocument();
    // The deepest drawdown is the all-time figure, always a loss.
    expect(screen.getByTestId("ledger-deepest")).toHaveTextContent(/^-2\.0%$/);
    expect(screen.getByTestId("ledger-deepest")).toHaveClass("text-loss");

    rerender(<LedgerLine {...BASE} pnl="-41.2000000000" ret="-0.0340000000" />);
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent(/^-41\.20USDT$/);
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
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^0\.0%$/);
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-gain");
    expect(screen.getByTestId("ledger-return")).not.toHaveClass("text-loss");
  });

  it("shows an em dash for an available balance nothing has synced", () => {
    render(<LedgerLine {...BASE} available={null} />);
    expect(screen.getByTestId("ledger-lead")).toHaveTextContent(/^—$/);
  });

  it("opens the balance's note behind an (i) after its title, only when there is one", () => {
    const { rerender } = render(<LedgerLine {...BASE} availableInfo={{ label: "Out of date", text: "Synced long ago." }} />);

    const button = within(term("ledger-group-available")).getByRole("button", { name: "Out of date" });
    expect(screen.queryByText("Synced long ago.")).toBeNull();
    fireEvent.click(button);
    expect(screen.getByText("Synced long ago.")).toBeInTheDocument();

    rerender(<LedgerLine {...BASE} />);
    expect(screen.queryByRole("button", { name: "Out of date" })).toBeNull();
  });

  it("names the range in the PnL's title only when it is not All", () => {
    const { rerender } = render(<LedgerLine {...BASE} range="All" />);
    expect(term("ledger-group-pnl")).toHaveTextContent(/^Total PnL$/);

    rerender(<LedgerLine {...BASE} range="7D" />);
    expect(term("ledger-group-pnl")).toHaveTextContent(/^Total PnL · 7D$/);
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
    expect(within(lines[0] as HTMLElement).getByTestId("ledger-lead")).toHaveTextContent("1,284.52USDT");
    // A BTC pool keeps its eight decimals; USDT's two would erase a BTC-sized PnL.
    expect(within(lines[1] as HTMLElement).getByTestId("ledger-lead")).toHaveTextContent("0.12345679BTC");
    expect(within(lines[1] as HTMLElement).getByTestId("ledger-pnl")).toHaveTextContent("+0.00012340BTC");
    expect(document.body).not.toHaveTextContent("1,284.64");
  });

  it("reads every word and number in the active language", async () => {
    await act(() => i18n.changeLanguage("es"));
    // Spanish groups thousands from five digits, not four: the locale decides, not this code.
    render(<LedgerLine {...BASE} range="1Y" available="12845.520000000000000000" />);

    expect(screen.getByTestId("ledger-lead")).toHaveTextContent(/^12\.845,52USDT$/);
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent(/^\+41,20USDT$/);
    expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^\+3,4%$/);
    expect(term("ledger-group-available")).toHaveTextContent("Saldo disponible");
    expect(term("ledger-group-pnl")).toHaveTextContent("PnL total · 1A");
    expect(term("ledger-group-drawdown")).toHaveTextContent("Caída máxima");
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

    it("has no balance group", () => {
      render(<LedgerLine {...WITHOUT_BALANCE} />);

      expect(groups()).toEqual(["ledger-group-pnl", "ledger-group-drawdown"]);
      expect(screen.queryByTestId("ledger-lead")).toBeNull();
    });

    it("still renders a null return as an em dash and an unreadable figure as an alert", () => {
      const { rerender } = render(<LedgerLine {...WITHOUT_BALANCE} ret={null} />);
      expect(screen.getByTestId("ledger-return")).toHaveTextContent(/^—$/);

      rerender(<LedgerLine {...WITHOUT_BALANCE} pnl="1e3" />);
      expect(screen.getByRole("alert")).toHaveTextContent("The figures could not be read.");
    });

  });
});
