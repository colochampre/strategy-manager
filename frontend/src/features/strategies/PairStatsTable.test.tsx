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
        pairs={[
          stat({ pair: "ETHUSDT", trades: 19, wins: 12, win_rate: "0.6315789474", pnl: "52.60" }),
          stat({ pair: "SOLUSDT", trades: 24, wins: 9, win_rate: "0.3750000000", pnl: "-5.30" }),
        ]}
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
    expect(headers).toEqual(["Pair", "Trades", "Win rate", "PnL USDT", "Return"]);
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
    expect(row.getAllByRole("cell")[4]).toHaveTextContent("—");
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
      "% acierto",
      "PnL USDT",
      "Rendimiento",
    ]);
  });
});

/** The cells of one pair's row, in column order: Pair, Trades, Win rate, PnL, Return. */
function cellsOf(pair: string): HTMLElement[] {
  return within(rowOf(pair)).getAllByRole("cell");
}

describe("PairStatsTable win rate column", () => {
  it("puts the Win rate column after Trades", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    expect(screen.queryAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Pair",
      "Trades",
      "Win rate",
      "PnL USDT",
      "Return",
    ]);
  });

  it("writes the rate unsigned in neutral ink", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades: 12, wins: 7, win_rate: "0.5833333333" })]} />);

    const cell = cellsOf("SOLUSDT")[2] as HTMLElement;
    expect(cell).toHaveTextContent("58.3%");
    expect(cell.textContent).not.toContain("+");
    expect(cell.className).not.toMatch(/text-(gain|loss)/);
  });

  it("writes a rate of 60.0% for three wins in five", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades: 5, wins: 3, win_rate: "0.6000000000" })]} />);

    expect(cellsOf("SOLUSDT")[2]).toHaveTextContent("60.0%");
  });

  it("the heading is Win rate in English and % acierto in Spanish", async () => {
    const { unmount } = render(<PairStatsTable currency="USDT" pairs={[stat()]} />);
    expect(screen.getByRole("columnheader", { name: "Win rate" })).toBeInTheDocument();
    unmount();

    await i18n.changeLanguage("es");
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    expect(screen.getByRole("columnheader", { name: "% acierto" })).toBeInTheDocument();
    // `toHaveTextContent` folds a no-break space into a plain one, so the exact text is compared.
    expect(cellsOf("SOLUSDT")[2]?.textContent).toBe("62,5 %");
  });

  it("the OPEN column is not built", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
    expect(screen.queryByRole("columnheader", { name: /open/i })).toBeNull();
  });

  it("hides no column and scrolls inside its own wrapper", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    const headers = screen.getAllByRole("columnheader");
    expect(headers).toHaveLength(5);
    for (const header of headers) {
      expect(header.className).not.toMatch(/(^|\s)(\w+:)?(hidden|sr-only)(\s|$)/);
    }
    expect(screen.getByRole("table").closest(".overflow-x-auto")).not.toBeNull();
  });

  it.each([
    ["above 1", "1.5000000000"],
    ["below 0", "-0.1000000000"],
  ])("shows the could-not-be-read state, and draws no row, for a win_rate %s", (_name, winRate) => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ win_rate: winRate })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByRole("row", { name: /SOLUSDT/ })).toBeNull();
  });

  it("does not draw wins 0 with a rate above 0", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades: 5000, wins: 0, win_rate: "0.0002000000" })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByRole("row", { name: /SOLUSDT/ })).toBeNull();
  });

  it("does not draw wins equal to trades with a rate below 1", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades: 5, wins: 5, win_rate: "0.9999999999" })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByRole("row", { name: /SOLUSDT/ })).toBeNull();
  });

  it("cuts the rate: 1,999 of 2,000 reads 99.9% and 2,000 of 2,000 reads 100.0%", () => {
    render(
      <PairStatsTable
        currency="USDT"
        pairs={[
          stat({ pair: "ETHUSDT", trades: 2000, wins: 1999, win_rate: "0.9995000000" }),
          stat({ pair: "SOLUSDT", trades: 2000, wins: 2000, win_rate: "1.0000000000" }),
        ]}
      />,
    );

    expect(cellsOf("ETHUSDT")[2]).toHaveTextContent("99.9%");
    expect(cellsOf("SOLUSDT")[2]).toHaveTextContent("100.0%");
  });

  it.each([
    ["5 trades, 3 wins, served 0.7000000000", 5, 3, "0.7000000000"],
    ["5 trades, 3 wins, served 0.6000000002, one unit past the tolerance", 5, 3, "0.6000000002"],
  ])("a ratio that does not match wins over trades is not drawn: %s", (_name, trades, wins, winRate) => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades, wins, win_rate: winRate })]} />);

    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.byPair.unreadable"));
    expect(screen.queryByRole("row", { name: /SOLUSDT/ })).toBeNull();
  });

  it("checks a trade count above a million in whole numbers, so the edge of the tolerance is still accepted", () => {
    // 5,000,000 trades and 7,920 wins: the ratio times the trades is exactly one unit of the last place off,
    // the edge. Multiplying floats puts it a hair past the edge and would refuse a row that is within it.
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades: 5_000_000, wins: 7920, win_rate: "0.0015840001" })]} />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(cellsOf("SOLUSDT")[2]).toHaveTextContent("0.1%");
  });

  it.each([
    ["7 of 12", 12, 7, "0.5833333333", "58.3%"],
    ["1,999 of 2,000", 2000, 1999, "0.9995000000", "99.9%"],
    ["1 of 3, rounded down", 3, 1, "0.3333333333", "33.3%"],
    ["1 of 3, one unit up", 3, 1, "0.3333333334", "33.3%"],
    ["3 of 5, at the edge", 5, 3, "0.6000000001", "60.0%"],
  ])("a ratio within one unit of its last place either way is drawn: %s", (_name, trades, wins, winRate, shown) => {
    render(<PairStatsTable currency="USDT" pairs={[stat({ trades, wins, win_rate: winRate })]} />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(cellsOf("SOLUSDT")[2]).toHaveTextContent(shown);
  });
});
