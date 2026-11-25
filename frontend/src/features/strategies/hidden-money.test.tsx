import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PairStatsTable } from "@/features/strategies/PairStatsTable";
import { ShareAmount } from "@/features/strategies/ShareAmount";
import type { ShareAmountView } from "@/features/strategies/ShareAmount";
import { money } from "@/features/strategies/StrategyCard";
import { TradeDetailDialog } from "@/features/strategies/TradeDetailDialog";
import { TradesTable } from "@/features/strategies/TradesTable";
import type { OperationFill, PairStat, StrategyTrade } from "@/shared/api/types";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, stubApi, unlock } from "@/test/harness";

/**
 * S1, L15: while the balances are hidden every page writes the user's own money as six stars: the PnL in currency, the
 * fees, the capital and the sizes of a trade, a strategy's capital and the margin of a share. The percentages, the
 * prices and the counts stay as they are.
 */

const ALLOCATION = "0b6f0000-0000-4000-8000-000000000001";
const STRATEGY = "11111111-1111-4111-8111-111111111111";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function trade(overrides: Partial<StrategyTrade> = {}): StrategyTrade {
  return {
    allocation_id: ALLOCATION,
    pair: "STXUSDT",
    direction: "LONG",
    opened_at: "2026-09-30T10:00:00Z",
    closed_at: "2026-09-30T12:30:00.000001Z",
    rehearsal: false,
    rehearsal_fill_price: null,
    base_currency: "STX",
    entry_price: "0.451200000000000000",
    exit_price: "0.463100000000000000",
    size: "1250.000000000000000000",
    fees: "0.630000000000000000",
    other_fees: [{ currency: "BNB", amount: "0.000120000000000000" }],
    pnl: "14.25",
    capital_at_open: "1000.000000000000000000",
    return: "0.0142450000",
    fees_complete: true,
    ...overrides,
  };
}

const fill = (): OperationFill => ({
  filled_at: "2026-09-30T10:00:00Z",
  side: "BUY",
  price: "0.451200000000000000",
  quantity: "1250.000000000000000000",
  fee: "0.310000000000000000",
  fee_currency: "USDT",
  rehearsal: false,
});

function stat(overrides: Partial<PairStat> = {}): PairStat {
  return { pair: "SOLUSDT", trades: 24, wins: 15, win_rate: "0.6250000000", pnl: "71.10", return: "0.0710000000", ...overrides };
}

beforeEach(async () => {
  unlock();
  window.localStorage.clear();
  useHiddenStore.setState({ hidden: true });
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});

describe("a card's money while the balances are hidden", () => {
  it("writes the amount as stars and keeps the currency beside them", () => {
    render(<span data-testid="figure">{money(1738.16, "USDT", "en", true)}</span>);

    const figure = screen.getByTestId("figure");
    expect(within(figure).getByText("******")).toBeInTheDocument();
    expect(figure.textContent).not.toContain("1,738.16");
    expect(figure.textContent).toContain("USDT");
  });

  it("writes the amount in full while they are shown", () => {
    useHiddenStore.setState({ hidden: false });
    render(<span data-testid="figure">{money(1738.16, "USDT", "en", true)}</span>);

    expect(screen.getByTestId("figure").textContent).toContain("+1,738.16");
  });
});

describe("the pair table while the balances are hidden", () => {
  it("masks the PnL of a pair and leaves its trades, win rate and return", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat(), stat({ pair: "ETHUSDT", pnl: "-5.30", return: "-0.0100000000" })]} />);

    const row = screen.getByRole("row", { name: /^SOLUSDT\b/ });
    expect(within(row).getAllByText("******")).toHaveLength(1);
    expect(within(row).queryByText("+71.10")).not.toBeInTheDocument();
    expect(within(row).getByText("24")).toBeInTheDocument();
    expect(within(row).getByText("62.5%")).toBeInTheDocument();
    expect(within(row).getByText("+7.1%")).toBeInTheDocument();
  });
});

describe("the share's margin while the balances are hidden", () => {
  it("writes the margin as stars and keeps the sentence", () => {
    const view: ShareAmountView = { kind: "known", amount: "335.00", currency: "USDT", staleAt: null, belowMinimum: null };
    render(<ShareAmount view={view} trailing={null} />);

    expect(screen.getByText("Margin: ****** USDT")).toBeInTheDocument();
    expect(screen.queryByText(/335/)).not.toBeInTheDocument();
  });
});

describe("the trade's dialog while the balances are hidden", () => {
  function open(row: StrategyTrade) {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ allocation_id: ALLOCATION, fills: [fill()], truncated: false }))),
    );
    renderAt(<TradeDetailDialog strategyId={STRATEGY} trade={row} currency="USDT" locale="en" onClose={() => undefined} />);
  }
  const figure = (label: string): HTMLElement => {
    const term = screen.getByText(label, { selector: "dt" });
    return term.nextElementSibling as HTMLElement;
  };

  it("masks the size, the fees, the PnL and the capital, and keeps the prices and the return", async () => {
    open(trade());

    expect(figure("Size (STX)").textContent).toContain("******");
    expect(figure("Fees paid (USDT)").textContent).toContain("******");
    expect(figure("Fees in other currencies").textContent).toContain("******");
    expect(figure("PnL (USDT)").textContent).toContain("******");
    expect(figure("Pool capital at open (USDT)").textContent).toContain("******");
    for (const label of ["Size (STX)", "Fees paid (USDT)", "PnL (USDT)", "Pool capital at open (USDT)"]) {
      expect(figure(label).textContent).not.toMatch(/\d/);
    }
    expect(figure("Entry price").textContent).toBe("0.4512");
    expect(figure("Exit price").textContent).toBe("0.4631");
    expect(figure("PnL %").textContent).toContain("+1.4%");
  });

  it("masks the quantity and the fee of each fill and keeps its price", async () => {
    open(trade());

    const table = await screen.findByRole("table");
    const row = within(table).getAllByRole("row")[1] as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]?.textContent).toBe("0.4512");
    expect(cells[3]?.textContent).toContain("******");
    expect(cells[3]?.textContent).not.toMatch(/\d/);
    expect(cells[4]?.textContent).toContain("******");
    expect(cells[4]?.textContent).toContain("USDT");
    expect(cells[4]?.textContent).not.toMatch(/\d/);
  });
});

describe("the closed trades table while the balances are hidden", () => {
  it("masks the size, the fees, the PnL and the capital of a row, and keeps the prices and the return", async () => {
    stubApi(HEALTH, [], undefined, {}, (url) => {
      if (!/\/performance\/strategies\/[^/]+\/trades$/.test(new URL(url, "http://localhost").pathname)) return undefined;
      return Promise.resolve(jsonResponse({ trades: [trade()], next_cursor: null }));
    });
    renderAt(<TradesTable strategyId={STRATEGY} currency="USDT" />);

    await screen.findByRole("table");
    const body = screen.getAllByRole("rowgroup")[1] as HTMLElement;
    const cells = within(within(body).getAllByRole("row")[0] as HTMLElement).getAllByRole("cell");
    // Opened, Closed, Pair, Side, Entry, Exit, Size, Fees, PnL, PnL %, Capital.
    expect(cells[4]?.textContent).toBe("0.4512");
    for (const index of [6, 7, 8, 10]) {
      expect(cells[index]?.textContent).toContain("******");
      expect(cells[index]?.textContent).not.toMatch(/\d/);
    }
    expect(cells[9]?.textContent).toContain("+1.4%");
  });
});
