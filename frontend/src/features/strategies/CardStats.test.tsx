import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { amountText, percentText } from "@/shared/lib/amount-text";
import {
  emptyPerformance,
  heldSubscription,
  jsonResponse,
  lock,
  pool,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  unlock,
} from "@/test/harness";

/**
 * The figures of each list as the approved tables draw them (S15, ex13 to ex15): the start date with its period in the
 * tooltip, one column each for the PnL, its percentage, the deepest fall, the win rate with its count, the live
 * subscribers and the capital, and the seat's settings on My subscriptions only. Days active and the bare count of
 * closed trades are not drawn.
 */

const ID = "11111111-1111-4111-8111-111111111111";

/** A record of six closed trades, four of them won, up 10.9 % with a 9.71 % deepest fall. */
const PUBLIC = publicStrategy({
  id: ID,
  created_at: "2026-10-12T10:00:00Z",
  closed_trade_count: 6,
  unleveraged_return_before_fees: "0.109",
  max_drawdown: "-0.0971",
  win_rate: "0.6666666667",
  live_subscribers: 2,
  capital: "1500",
});

/** A report of the reader's own: 67.20 USDT made, +10.9 %, a 9.71 % deepest fall, 4 of 6 trades won. */
function ownReport() {
  return {
    ...emptyPerformance("bybit", "usdt-m", "USDT"),
    strategy_id: ID,
    trade_count: 6,
    total_pnl: "67.2",
    max_drawdown: "-0.0971",
    by_pair: [
      { pair: "SOLUSDT", trades: 4, wins: 3, win_rate: "0.75", pnl: "50", return: "0.08" },
      { pair: "ETHUSDT", trades: 2, wins: 1, win_rate: "0.5", pnl: "17.2", return: "0.029" },
    ],
    ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({
      range,
      pnl: range === "All" ? "67.2" : "1",
      return: range === "All" ? "0.109" : "0.001",
      trade_count: 6,
    })),
  };
}

const AUTHORED = {
  id: ID,
  name: "Alpha",
  exchange: "bybit",
  venue: "usdt-m",
  settlement_currency: "USDT",
  fill_mode: "SKIP",
  subscription: null,
  enabled: true,
  archived_at: null,
  allowed_pairs: ["SOLUSDT"],
  uptime: { seconds: 12 * 86_400, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
  visibility: "PRIVATE",
  share_token: null,
  secret_last4: "x4F2",
  description: null,
  subscribers: 3,
  live_subscribers: 2,
  created_at: "2026-09-01T10:00:00Z",
  capital: "1500",
  stop_loss_pct: "10.00",
};

function serve() {
  return stubApi(
    { kind: "ok", body: { status: "ok", dry_run: true } },
    [],
    { kind: "ok", body: [pool("bybit", "usdt-m")] },
    {},
    (url) => {
      const path = new URL(url, "http://localhost").pathname;
      if (path.endsWith("/api/public/strategies")) return Promise.resolve(jsonResponse([PUBLIC]));
      if (path.endsWith("/api/subscriptions/held")) return Promise.resolve(jsonResponse([heldSubscription()]));
      if (path.endsWith(`/performance/strategies/${ID}`)) return Promise.resolve(jsonResponse(ownReport()));
      if (path.endsWith("/api/strategies")) return Promise.resolve(jsonResponse([AUTHORED]));
      return undefined;
    },
  );
}

/** The percent the table writes: the number with its sign, then the percent sign right after it (L21). */
const pct = (ratio: number) => `${percentText(ratio, "en", false)}%`;
const usdt = (amount: number, signed = false) => amountText(amount, "USDT", "en", signed);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Date.UTC(2026, 10, 17, 12));
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  lock();
});

describe("a row on Explore", () => {
  it("dates the strategy from its creation and draws the record in its columns, with no settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies/explore");
    const row = await screen.findByTestId("public-strategy-row");

    expect(within(row).getByTestId("public-age")).toHaveTextContent("Oct 12, 2026");
    expect(within(row).getByTestId("public-return")).toHaveTextContent(pct(0.109));
    // The public record carries no money: the author's PnL is theirs alone.
    expect(within(row).queryByTestId("public-pnl")).toBeNull();
    expect(within(row).getByTestId("public-deepest")).toHaveTextContent(pct(-0.0971));
    expect(within(row).getByTestId("public-winrate")).toHaveTextContent("66.7%");
    expect(within(row).getByTestId("public-wins")).toHaveTextContent("4/6");
    expect(within(row).getByTestId("public-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("public-capital").textContent).toBe(usdt(1500));

    expect(within(row).queryByTestId("public-share")).toBeNull();
    expect(within(row).queryByTestId("public-uptime")).toBeNull();
    expect(within(row).queryByTestId("public-trades")).toBeNull();
  });
});

describe("a row on My subscriptions", () => {
  it("speaks of the reader's own seat: their PnL, return, deepest fall and trades, then AuM and the seat's settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies");
    const row = await screen.findByTestId("subscription-row");

    expect(within(row).getByTestId("subscription-age")).toHaveTextContent("Oct 27, 2026");

    await waitFor(() => expect(within(row).getByTestId("subscription-pnl").textContent).toBe(usdt(67.2, true)));
    expect(within(row).getByTestId("subscription-return")).toHaveTextContent(pct(0.109));
    expect(within(row).getByTestId("subscription-deepest")).toHaveTextContent(pct(-0.0971));
    expect(within(row).getByTestId("subscription-winrate")).toHaveTextContent("66.7%");
    expect(within(row).getByTestId("subscription-wins")).toHaveTextContent("4/6");
    expect(within(row).getByTestId("subscription-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("subscription-capital").textContent).toBe(usdt(1500));

    expect(within(row).getByTestId("subscription-share")).toHaveTextContent("30%");
    expect(within(row).getByTestId("subscription-leverage")).toHaveTextContent("x1");

    expect(within(row).queryByTestId("subscription-uptime")).toBeNull();
    expect(within(row).queryByTestId("subscription-trades")).toBeNull();
  });
});

describe("a row on My strategies", () => {
  it("joins the author's PnL and return in their columns and draws no settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    expect(within(row).getByTestId("strategy-age")).toHaveTextContent("Sep 01, 2026");

    await waitFor(() => expect(within(row).getByTestId("strategy-pnl").textContent).toBe(usdt(67.2, true)));
    expect(within(row).getByTestId("strategy-return")).toHaveTextContent(pct(0.109));
    expect(within(row).getByTestId("strategy-wins")).toHaveTextContent("4/6");
    expect(within(row).getByTestId("strategy-capital").textContent).toBe(usdt(1500));

    expect(within(row).queryByTestId("strategy-share")).toBeNull();
    expect(within(row).queryByTestId("strategy-leverage")).toBeNull();
    expect(within(row).queryByTestId("strategy-uptime")).toBeNull();
  });
});
