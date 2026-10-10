import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PairStatsTable } from "@/features/strategies/PairStatsTable";
import type { PairStat } from "@/shared/api/types";
import i18n from "@/shared/i18n";

function stat(overrides: Partial<PairStat> = {}): PairStat {
  return {
    pair: "SOLUSDT",
    trades: 24,
    wins: 15,
    win_rate: "0.6250000000",
    pnl: "71.10",
    return: "0.0710000000",
    ...overrides,
  };
}

function rowOf(pair: string): HTMLElement {
  return screen.getByRole("row", { name: new RegExp(`^${pair}\\b`) });
}

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("PairStatsTable", () => {
  it("test_pair_removed_from_allowlist_still_shown_with_historical_stats", () => {
    // The table is given the report's `by_pair` and nothing else: no allowed-pairs list reaches it.
    // A strategy whose allowed pairs are now just ETHUSDT still lists the SOLUSDT it traded before.
    render(
      <PairStatsTable
        currency="USDT"
        pairs={[stat({ pair: "ETHUSDT", trades: 19, pnl: "52.60" }), stat({ pair: "SOLUSDT", trades: 24, pnl: "-5.30" })]}
      />,
    );

    const removed = within(rowOf("SOLUSDT"));
    expect(removed.getByText("24")).toBeInTheDocument();
    expect(removed.getByText("-5.30")).toBeInTheDocument();
    expect(within(rowOf("ETHUSDT")).getByText("+52.60")).toBeInTheDocument();
  });

  it("names the columns and says which currency the PnL is in", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toEqual(["Pair", "Trades", "PnL USDT", "Return"]);
  });

  it("writes a coin-margined pool's PnL in its own currency with eight decimals", () => {
    render(<PairStatsTable currency="BTC" pairs={[stat({ pair: "BTCUSD", pnl: "0.00123400" })]} />);

    expect(screen.getByRole("columnheader", { name: "PnL BTC" })).toBeInTheDocument();
    expect(within(rowOf("BTCUSD")).getByText("+0.00123400")).toBeInTheDocument();
  });

  it("lists the pairs in the order the server gave them and in the venue's spelling", () => {
    render(
      <PairStatsTable
        currency="USDT"
        pairs={[stat({ pair: "STXUSDT" }), stat({ pair: "AAVEUSDT" }), stat({ pair: "ETHUSDT" })]}
      />,
    );

    const body = screen.getAllByRole("rowgroup")[1] as HTMLElement;
    const pairs = within(body)
      .getAllByRole("row")
      .map((row) => within(row).getAllByRole("cell")[0]?.textContent);
    expect(pairs).toEqual(["STXUSDT", "AAVEUSDT", "ETHUSDT"]);
  });

  it("shows a return as a signed percentage", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ return: "-0.0124000000" })]} />);

    expect(within(rowOf("SOLUSDT")).getByText("-1.2%")).toBeInTheDocument();
  });

  it("shows an em dash, never a zero, for a pair with no return", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ return: null })]} />);

    const row = within(rowOf("SOLUSDT"));
    expect(row.getAllByRole("cell")[3]).toHaveTextContent("—");
    expect(row.queryByText("0.0%")).toBeNull();
    expect(row.getByText(i18n.t("strategies.performance.byPair.noReturn"))).toBeInTheDocument();
  });

  it("says so, and draws no table, when one figure cannot be read", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ pair: "ETHUSDT", pnl: "1e3" }), stat({ pair: "SOLUSDT" })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByRole("row", { name: /ETHUSDT/ })).toBeNull();
    expect(screen.queryByText("1,000.00")).toBeNull();
  });

  it("says so when a return cannot be read, instead of drawing a number", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ return: "n/a" })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByText("71.10")).toBeNull();
  });

  it("says no pair has closed a trade when the list is empty", () => {
    render(<PairStatsTable currency="USDT" pairs={[]} />);

    expect(screen.getByText(i18n.t("strategies.performance.byPair.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("is titled and labelled in Spanish", async () => {
    await i18n.changeLanguage("es");
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    expect(screen.getByRole("heading", { name: "Por par" })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Par",
      "Operaciones",
      "PnL USDT",
      "Rendimiento",
    ]);
  });
});
