import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyPerformance } from "@/features/strategies/StrategyPerformance";
import type { PairStat, StrategyPerformance as StrategyReport } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { emptyPerformance, jsonResponse, lock, renderAt, stubApi, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function report(overrides: Partial<StrategyReport> = {}): StrategyReport {
  const base = emptyPerformance("bybit", "usdt-m", "USDT");
  const today = new Date();
  const recent = new Date(today.getTime() - 3 * 86_400_000).toISOString().slice(0, 10);
  return {
    ...base,
    strategy_id: ID,
    trade_count: 4,
    total_pnl: "118.40",
    max_drawdown: "-0.0240000000",
    ranges: [
      { range: "7D", pnl: "30.00", return: "0.0250000000", trade_count: 1 },
      { range: "30D", pnl: "70.00", return: "0.0600000000", trade_count: 2 },
      { range: "90D", pnl: "90.00", return: "0.0800000000", trade_count: 3 },
      { range: "1Y", pnl: "118.40", return: "0.0960000000", trade_count: 4 },
      { range: "All", pnl: "118.40", return: "0.0960000000", trade_count: 4 },
    ],
    curve: [{ date: recent, daily_return: "0.025", index: "1.025", drawdown: "0" }],
    monthly: [{ year: today.getUTCFullYear(), month: today.getUTCMonth() + 1, return: "0.0250000000" }],
    by_pair: [
      { pair: "SOLUSDT", trades: 3, wins: 2, win_rate: "0.6666666667", pnl: "71.10", return: "0.0710000000" },
      { pair: "BTCUSDT", trades: 1, wins: 0, win_rate: "0.0000000000", pnl: "-5.30", return: null },
    ] satisfies PairStat[],
    ...overrides,
  };
}

function serve(answer: () => Promise<Response>) {
  const requests: string[] = [];
  stubApi(HEALTH, [], undefined, {}, (url) => {
    if (!url.includes(`/performance/strategies/${ID}`)) return undefined;
    requests.push(url);
    return answer();
  });
  return requests;
}

const ledger = () => (screen.getByTestId("ledger-line").textContent ?? "").replace(/\s+/g, " ").trim();

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyPerformance", () => {
  it("shows one strategy's PnL, its contribution to the pool and its deepest drop, with no balance", async () => {
    serve(() => Promise.resolve(jsonResponse(report())));
    renderAt(<StrategyPerformance strategyId={ID} />);

    await screen.findByTestId("ledger-line");

    expect(ledger()).toBe("PnL 30D +70.00 · contribution to the pool 30D +6.0% · deepest -2.4%");
    expect(screen.queryByTestId("ledger-lead")).toBeNull();
    expect(screen.queryByText(/available/)).toBeNull();
  });

  it("follows the range selector in the ledger line and in the chart", async () => {
    serve(() => Promise.resolve(jsonResponse(report())));
    renderAt(<StrategyPerformance strategyId={ID} />);
    await screen.findByTestId("ledger-line");

    fireEvent.click(screen.getByRole("button", { name: "7D" }));

    expect(ledger()).toBe("PnL 7D +30.00 · contribution to the pool 7D +2.5% · deepest -2.4%");
    expect(screen.getByRole("button", { name: "7D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("return-curve")).toBeInTheDocument();
  });

  it("draws the strategy's own curve and months, under a title that says it is a contribution", async () => {
    serve(() => Promise.resolve(jsonResponse(report())));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByRole("heading", { name: "Contribution to the pool, compounded" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Return of the strategies, compounded" })).toBeNull();
    expect(Number(screen.getByTestId("return-curve").getAttribute("data-final-return"))).toBeCloseTo(0.025, 6);
    expect(screen.getByRole("heading", { name: "Month by month" })).toBeInTheDocument();
    expect(screen.getByText("1 of 1 month positive · best +2.5% · worst +2.5%")).toBeInTheDocument();
  });

  it("lists the by-pair table of the same report, a pair without a return as a dash", async () => {
    const requests = serve(() => Promise.resolve(jsonResponse(report())));
    renderAt(<StrategyPerformance strategyId={ID} />);

    const table = await screen.findByRole("table", { name: "By pair" });

    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1] as HTMLElement).getByText("+71.10")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getAllByRole("cell")[3]).toHaveTextContent("—");
    // One request feeds the whole section.
    expect(requests).toHaveLength(1);
  });

  it("says what the curve leaves out: open trades and trades without capital at open", async () => {
    const base = report();
    serve(() =>
      Promise.resolve(jsonResponse({ ...base, excluded: { ...base.excluded, open_trade_count: 2, no_capital_at_open: 1 } })),
    );
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(
      await screen.findByText(/2 open trades not in the curve · 1 trade without capital at open/),
    ).toBeInTheDocument();
  });

  it("says no closed trades yet for a strategy with an empty ledger, with an empty by-pair section", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: [] }),
      ),
    );
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByText("No closed trades yet")).toBeInTheDocument();
    expect(screen.getByText(i18n.t("strategies.performance.byPair.empty"))).toBeInTheDocument();
    expect(ledger()).toBe("PnL 30D 0.00 · contribution to the pool 30D 0.0% · deepest 0.0%");
  });

  it("says the figures cannot be read when the chosen range is missing from the report", async () => {
    const base = report();
    serve(() => Promise.resolve(jsonResponse({ ...base, ranges: base.ranges.filter((entry) => entry.range !== "30D") })));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("overview.ledger.unreadable"));
    expect(screen.queryByText(/contribution to the pool 30D/)).toBeNull();
  });

  it("says it is loading, then shows nothing of a wrong shape", async () => {
    serve(() => new Promise<Response>(() => undefined));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByRole("status")).toHaveTextContent(i18n.t("strategies.performance.loading"));
    expect(screen.queryByTestId("ledger-line")).toBeNull();
  });

  it("says the report could not be loaded when the request fails", async () => {
    serve(() => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.error"));
    expect(screen.queryByTestId("ledger-line")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("offers Try again when the report fails, and shows the report once the second read succeeds", async () => {
    let failing = true;
    const requests = serve(() =>
      Promise.resolve(failing ? jsonResponse({ detail: "boom" }, 500) : jsonResponse(report())),
    );
    renderAt(<StrategyPerformance strategyId={ID} />);
    await screen.findByText(i18n.t("strategies.performance.error"));

    failing = false;
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.performance.retry") }));

    expect(await screen.findByTestId("ledger-line")).toBeInTheDocument();
    expect(requests).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps Try again visible and the error shown when the second read fails too", async () => {
    const requests = serve(() => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    renderAt(<StrategyPerformance strategyId={ID} />);
    await screen.findByText(i18n.t("strategies.performance.error"));

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.performance.retry") }));

    await waitFor(() => expect(requests).toHaveLength(2));
    expect(await screen.findByRole("button", { name: i18n.t("strategies.performance.retry") })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.error"));
  });

  it("says the report could not be loaded for a body that has no by_pair, never a half report", async () => {
    const { by_pair: _dropped, ...withoutPairs } = report();
    serve(() => Promise.resolve(jsonResponse(withoutPairs)));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.error"));
    expect(screen.queryByTestId("ledger-line")).toBeNull();
  });

  it("says no report exists for a strategy the server does not know", async () => {
    serve(() => Promise.resolve(jsonResponse({ detail: "no such strategy" }, 404)));
    renderAt(<StrategyPerformance strategyId={ID} />);

    expect(await screen.findByText(i18n.t("strategies.performance.noReport"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is written in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve(() => Promise.resolve(jsonResponse(report())));
    renderAt(<StrategyPerformance strategyId={ID} />);

    await screen.findByTestId("ledger-line");

    expect(ledger()).toContain("aporte al pool 30D");
    expect(screen.getByRole("heading", { name: "Aporte al pool, compuesto" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Por par" })).toBeInTheDocument();
  });
});
