import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyReportViews } from "@/features/strategies/StrategyReportViews";
import type { PublicStrategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import {
  emptyPerformance,
  heldSubscription,
  jsonResponse,
  lock,
  publicRecord,
  publicStrategy,
  renderAt,
  stubApi,
  unlock,
} from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const STRATEGY = publicStrategy({ id: ID }) as PublicStrategy;

function daysAgo(count: number): string {
  return new Date(Date.now() - count * 86_400_000).toISOString().slice(0, 10);
}

/** The record, with its dates counted back from today so the default 30D window holds them. */
function liveRecord(overrides: Record<string, unknown> = {}) {
  return publicRecord({
    origin: daysAgo(20),
    curve: [
      { date: daysAgo(20), daily_return: "0", index: "0", drawdown: "0" },
      { date: daysAgo(10), daily_return: "0.04", index: "0.04", drawdown: "0" },
      { date: daysAgo(3), daily_return: "0.01", index: "0.0505", drawdown: "-0.02" },
    ],
    ...overrides,
  });
}

/** The reader's own report: money in USDT, one pair, a curve of its own. */
function myReport(overrides: Record<string, unknown> = {}) {
  return {
    ...emptyPerformance("bybit", "usdt-m", "USDT"),
    strategy_id: ID,
    trade_count: 2,
    total_pnl: "41.25",
    max_drawdown: "-0.0100000000",
    ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({ range, pnl: "41.25", return: "0.0200000000", trade_count: 2 })),
    curve: [{ date: daysAgo(5), daily_return: "0.02", index: "0.02", drawdown: "0" }],
    monthly: [{ year: 2026, month: 11, return: "0.0200000000" }],
    // Two pairs: the By pair section is drawn only when more than one has traded.
    by_pair: [
      { pair: "XRPUSDT", trades: 2, wins: 2, win_rate: "1", pnl: "41.25", return: "0.0200000000" },
      { pair: "LTCUSDT", trades: 1, wins: 0, win_rate: "0", pnl: "-3.00", return: "-0.0010000000" },
    ],
    ...overrides,
  };
}

interface Serve {
  record?: () => Promise<Response>;
  held?: unknown[];
  mine?: () => Promise<Response>;
  me?: Record<string, unknown>;
}

function serve({ record, held = [], mine, me }: Serve = {}) {
  const requests: string[] = [];
  stubApi(HEALTH, [], undefined, {}, (url) => {
    if (url.endsWith(`/public/strategies/${ID}/record`)) {
      requests.push(url);
      return record?.() ?? Promise.resolve(jsonResponse(liveRecord()));
    }
    if (url.endsWith("/api/subscriptions/held")) return Promise.resolve(jsonResponse(held));
    if (url.includes(`/performance/strategies/${ID}`)) {
      requests.push(url);
      return mine?.() ?? Promise.resolve(jsonResponse(myReport()));
    }
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "bea@example.com", is_admin: false, mode: "LIVE", dry_run_brake: false, display_name: "Bea", ...me }),
      );
    }
    return undefined;
  });
  return requests;
}

const seat = (overrides: Record<string, unknown> = {}) => [heldSubscription({ strategy_id: ID, created_at: `${daysAgo(10)}T10:00:00Z`, ...overrides })];
const mineButton = () => screen.findByRole("button", { name: "My results" });
const recordButton = () => screen.findByRole("button", { name: "Strategy record" });
/** Lets a request that should NOT be sent reach the network if it was going to. */
const tick = () => new Promise((resolve) => setTimeout(resolve, 20));

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyReportViews", () => {
  it("draws the record for a reader with no seat: curve, months and pairs, no money, no selector", async () => {
    serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByTestId("return-curve")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Month by month" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /^SOLUSDT\b/ })).toBeInTheDocument();
    expect(screen.getByTestId("record-return")).toHaveTextContent("+5.1%");
    // No money anywhere: no PnL column, no amount, no currency.
    expect(screen.queryByRole("columnheader", { name: /PnL/ })).toBeNull();
    expect(screen.queryByText(/\bUSDT\b/)).toBeNull();
    expect(screen.queryByRole("button", { name: "My results" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Strategy record" })).toBeNull();
  });

  it("asks nothing of the reader's own report when there is no seat", async () => {
    const requests = serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByTestId("return-curve");
    await tick();

    expect(requests.some((url) => url.includes("/performance/"))).toBe(false);
  });

  it("follows the range selector in the record's return", async () => {
    serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByTestId("return-curve");

    fireEvent.click(screen.getByRole("button", { name: "7D" }));

    expect(screen.getByTestId("record-return")).toHaveTextContent("+1.0%");
    fireEvent.click(screen.getByRole("button", { name: "30D" }));
  });

  it("draws the record line as the cards' icons over their values, and keeps the (i) on the return", async () => {
    serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    const line = await screen.findByTestId("record-line");

    const returnTerm = screen.getByTestId("record-return").previousElementSibling as HTMLElement;
    expect(returnTerm.querySelector("svg.lucide-trending-up")).not.toBeNull();
    expect(returnTerm.textContent).toBe("");
    const deepest = within(line).getByTestId("record-deepest");
    const deepestTerm = deepest.previousElementSibling as HTMLElement;
    expect(deepestTerm.querySelector("svg.lucide-trending-down")).not.toBeNull();
    expect(deepest).toHaveClass("text-loss");
    expect(within(deepestTerm).getByRole("img", { name: "Drawdown" })).toBeInTheDocument();
    // The unleveraged, before-fees disclosure stays with the return.
    expect(within(returnTerm).getByRole("button", { name: i18n.t("strategies.public.returnInfo") })).toBeInTheDocument();
    expect(line.textContent).not.toMatch(/return|deepest/i);
  });

  it("names the range in the record's return tooltip only when it is not All", async () => {
    serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByTestId("record-line");
    const name = () =>
      within(screen.getByTestId("record-return").previousElementSibling as HTMLElement).getByRole("img").getAttribute("aria-label");

    fireEvent.click(screen.getByRole("button", { name: "7D" }));
    expect(name()).toBe("Return, last 7 days");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(name()).toBe("Return");
    // The range is one choice for the whole panel: put it back where the other tests expect it.
    fireEvent.click(screen.getByRole("button", { name: "30D" }));
  });

  it("opens a subscriber on My results, with the selector and My results pressed", async () => {
    serve({ held: seat() });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await mineButton()).toHaveAttribute("aria-pressed", "true");
    expect(await recordButton()).toHaveAttribute("aria-pressed", "false");
    // Their own money, in their pool's currency, and their own pair.
    expect(await screen.findByRole("row", { name: /^XRPUSDT\b/ })).toBeInTheDocument();
    expect(screen.getByText("PnL USDT")).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /^SOLUSDT\b/ })).toBeNull();
  });

  it("does not ask for the record while My results is the view", async () => {
    const requests = serve({ held: seat() });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByRole("row", { name: /^XRPUSDT\b/ });
    await tick();

    expect(requests.some((url) => url.endsWith("/record"))).toBe(false);
  });

  it("switches to the record and never draws both in one chart", async () => {
    serve({ held: seat() });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByRole("row", { name: /^XRPUSDT\b/ });
    expect(screen.getAllByTestId("return-curve")).toHaveLength(1);

    fireEvent.click(await recordButton());

    expect(await screen.findByRole("row", { name: /^SOLUSDT\b/ })).toBeInTheDocument();
    expect(screen.getAllByTestId("return-curve")).toHaveLength(1);
    expect(screen.queryByRole("row", { name: /^XRPUSDT\b/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Strategy record" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "My results" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/\bUSDT\b/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "My results" }));
    expect(await screen.findByRole("row", { name: /^XRPUSDT\b/ })).toBeInTheDocument();
    expect(screen.getAllByTestId("return-curve")).toHaveLength(1);
  });

  it("marks the day the seat began on the record's curve", async () => {
    serve({ held: seat() });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    fireEvent.click(await recordButton());

    const marker = await screen.findByTestId("seat-marker");
    expect(marker).toBeInTheDocument();
    expect(screen.getByText(/^You joined on /)).toBeInTheDocument();
  });

  it("marks nothing when the seat began before the window", async () => {
    serve({ held: seat({ created_at: `${daysAgo(200)}T10:00:00Z` }) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    fireEvent.click(await recordButton());
    await screen.findByTestId("return-curve");

    expect(screen.queryByTestId("seat-marker")).toBeNull();
  });

  it("marks nothing for a reader with no seat", async () => {
    serve();
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByTestId("return-curve");

    expect(screen.queryByTestId("seat-marker")).toBeNull();
  });

  it("gives the author no selector: their own page is where their results are", async () => {
    serve({ held: seat({ authored: true }) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);
    await screen.findByTestId("return-curve");
    await tick();

    expect(screen.queryByRole("button", { name: "My results" })).toBeNull();
  });

  it("says in words that the record has no closed trade, and draws no chart", async () => {
    serve({ record: () => Promise.resolve(jsonResponse(publicRecord({ origin: null, closed_trade_count: 0, curve: [], monthly: [], by_pair: [] }))) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByText(/no closed real trade yet/)).toBeInTheDocument();
    expect(screen.queryByTestId("return-curve")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("says in words that My results has no trade yet", async () => {
    serve({ held: seat(), mine: () => Promise.resolve(jsonResponse(myReport({ trade_count: 0, curve: [], monthly: [], by_pair: [] }))) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByText("You have no closed trade in this strategy yet.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("answers a record that is gone calmly, not with a crash", async () => {
    serve({ record: () => Promise.resolve(jsonResponse({ detail: "no such strategy" }, 404)) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByText("This strategy's record is not available.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a record that is malformed, with a retry", async () => {
    serve({ record: () => Promise.resolve(jsonResponse(liveRecord({ max_drawdown: -0.02 }))) });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The strategy's record could not be loaded.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByTestId("return-curve")).toBeNull();
  });

  it("reads in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve({ held: seat() });
    renderAt(<StrategyReportViews strategy={STRATEGY} />);

    expect(await screen.findByRole("button", { name: "Mis resultados" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Historial de la estrategia" }));
    await waitFor(() => expect(screen.getByText(/^Usted se suscribió el /)).toBeInTheDocument());
  });
});
