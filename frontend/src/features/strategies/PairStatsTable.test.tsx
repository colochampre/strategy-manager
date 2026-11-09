import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PairStatsTable as BareTable } from "@/features/strategies/PairStatsTable";
import type { PairStat } from "@/shared/api/types";
import i18n from "@/shared/i18n";

type TableProps = Parameters<typeof BareTable>[0];

/**
 * The table, with a second pair added to a list of one: the section shows only with more than one pair that
 * has traded, and most of these tests are about a row, not about that rule (which has its own describe below).
 */
function PairStatsTable(props: TableProps) {
  const pairs = props.pairs.length === 1 ? [...props.pairs, stat({ pair: "FILLERUSDT" })] : props.pairs;
  return <BareTable {...props} pairs={pairs} />;
}

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

/** The columns' names in order; each is the accessible name of the icon that stands for it. */
function headerNames(): (string | null)[] {
  return screen.getAllByRole("columnheader").map((header) => within(header).getByRole("img").getAttribute("aria-label"));
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

    expect(headerNames()).toEqual(["Pair", "Trades", "Win rate", "PnL USDT", "Return"]);
  });

  it("draws each column's name as an icon, with the name as its accessible name", () => {
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual(["", "", "", "", ""]);
    expect(headers.map((header) => within(header).getByRole("img").getAttribute("aria-label"))).toEqual([
      "Pair",
      "Trades",
      "Win rate",
      "PnL USDT",
      "Return",
    ]);
    for (const header of headers) expect(header.querySelector("svg")).not.toBeNull();
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

  describe("shows only with more than one pair that has traded", () => {
    const heading = () => screen.queryByRole("heading", { name: "By pair" });

    it("is absent with no pair, and says nothing in its place", () => {
      const { container } = render(<BareTable currency="USDT" pairs={[]} />);

      expect(heading()).toBeNull();
      expect(screen.queryByRole("table")).toBeNull();
      expect(container).toBeEmptyDOMElement();
    });

    it("is absent with one pair, which the view's header already says", () => {
      const { container } = render(<BareTable currency="USDT" pairs={[stat()]} />);

      expect(heading()).toBeNull();
      expect(screen.queryByRole("table")).toBeNull();
      expect(container).toBeEmptyDOMElement();
    });

    it("is absent with two pairs when only one of them has a trade", () => {
      render(<BareTable currency="USDT" pairs={[stat(), stat({ pair: "ETHUSDT", trades: 0, wins: 0, win_rate: "0.0000000000" })]} />);

      expect(heading()).toBeNull();
    });

    it("is drawn with two pairs that have traded", () => {
      render(<BareTable currency="USDT" pairs={[stat(), stat({ pair: "ETHUSDT" })]} />);

      expect(heading()).toBeInTheDocument();
      expect(screen.getByRole("table", { name: "By pair" })).toBeInTheDocument();
    });

    it("is drawn, as an alert, when there are two pairs and a figure cannot be read", () => {
      render(<BareTable currency="USDT" pairs={[stat({ pnl: "1e3" }), stat({ pair: "ETHUSDT" })]} />);

      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    it("is absent for a record of one pair, which has no money column", () => {
      const { pnl: _pnl, ...record } = stat();
      const { container } = render(<BareTable pairs={[record]} />);

      expect(container).toBeEmptyDOMElement();
    });
  });

  it("is titled and labelled in Spanish", async () => {
    await i18n.changeLanguage("es");
    render(<PairStatsTable currency="USDT" pairs={[stat()]} />);

    expect(screen.getByRole("heading", { name: "Por par" })).toBeInTheDocument();
    expect(headerNames()).toEqual([
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

    expect(headerNames()).toEqual([
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
    const winRate = screen.getByRole("columnheader", { name: "Win rate" });
    // A trophy, the owner's choice (L.11).
    expect(winRate.querySelector("svg.lucide-trophy")).not.toBeNull();
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

  it("without a currency it is a record: no PnL column, no money, the return and the rate as ever", () => {
    const { pnl: _pnl, ...record } = stat({ pair: "ETHUSDT", trades: 2, wins: 1, win_rate: "0.5", return: "0.04" });
    render(<PairStatsTable pairs={[record]} />);

    expect(screen.queryByRole("columnheader", { name: /PnL/ })).toBeNull();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
    const cells = cellsOf("ETHUSDT");
    expect(cells).toHaveLength(4);
    expect(cells[1]).toHaveTextContent("2");
    expect(cells[2]).toHaveTextContent("50.0%");
    expect(cells[3]).toHaveTextContent("+4.0%");
    expect(screen.queryByText(/\bUSDT\b/)).toBeNull();
  });

  it("with a currency a row that carries no PnL cannot be read", () => {
    const { pnl: _pnl, ...record } = stat();
    render(<PairStatsTable currency="USDT" pairs={[record]} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
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
