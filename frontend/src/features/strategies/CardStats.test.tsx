import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
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
 * The card as the owner asked for it on 2026-11-17, after TradingView's strategy tester: the age moves to the market
 * line as a date range, days active and the bare closed-trade count go, and the figures are grouped under one label
 * each (Total PnL, Max drawdown, Profitable trades, AuM, and the seat's settings on My subscriptions only).
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

const en = (key: string) => i18n.t(key);
const pct = (ratio: number) => percentText(ratio, "en");
const usdt = (amount: number, signed = false) => `${amountText(amount, "USDT", "en", signed)} USDT`;

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

/** The card's group under `label`: its label and its values. */
function group(row: HTMLElement, testId: string, label: string) {
  const found = within(row).getByTestId(testId);
  expect(within(found).getByText(label)).toBeInTheDocument();
  return found;
}

describe("a card on Explore", () => {
  it("dates the strategy on its market line and groups the record under four labels, with no settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies/explore");
    const row = await screen.findByTestId("public-strategy-row");

    const market = within(row).getByTestId("public-market");
    expect(market).toHaveTextContent("bybit · usdt-m · USDT");
    expect(within(market).getByTestId("public-age")).toHaveTextContent("Oct 12, 2026 – Nov 17, 2026");
    expect(within(market).getByRole("img", { name: en("strategies.card.age") })).toBeInTheDocument();

    const pnl = group(row, "public-group-pnl", en("strategies.card.totalPnl"));
    expect(within(pnl).getByTestId("public-return")).toHaveTextContent(pct(0.109));
    // The public record carries no money: the author's PnL is theirs alone.
    expect(within(row).queryByTestId("public-pnl")).toBeNull();

    const drawdown = group(row, "public-group-drawdown", en("strategies.card.maxDrawdown"));
    expect(within(drawdown).getByTestId("public-deepest")).toHaveTextContent(pct(-0.0971));

    const profitable = group(row, "public-group-profitable", en("strategies.card.profitableTrades"));
    expect(within(profitable).getByTestId("public-winrate")).toHaveTextContent("66.7%");
    expect(within(profitable).getByTestId("public-wins")).toHaveTextContent("4/6");

    const aum = group(row, "public-group-aum", en("strategies.card.aum"));
    expect(within(aum).getByTestId("public-subscribers")).toHaveTextContent(/^2$/);
    expect(within(aum).getByRole("img", { name: en("strategies.card.subscribers") })).toBeInTheDocument();
    expect(within(aum).getByTestId("public-capital")).toHaveTextContent(usdt(1500));

    expect(within(row).queryByTestId("public-group-setup")).toBeNull();
    expect(within(row).queryByTestId("public-uptime")).toBeNull();
    expect(within(row).queryByTestId("public-trades")).toBeNull();
  });
});

describe("a card on My subscriptions", () => {
  it("speaks of the reader's own seat: their PnL, return, deepest fall and trades, then AuM and the seat's settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies");
    const row = await screen.findByTestId("subscription-row");

    const market = within(row).getByTestId("subscription-market");
    expect(market).toHaveTextContent("bybit · usdt-m · USDT");
    expect(within(market).getByTestId("subscription-age")).toHaveTextContent("Oct 27, 2026 – Nov 17, 2026");
    expect(within(market).getByRole("img", { name: en("strategies.card.subscribed") })).toBeInTheDocument();

    const pnl = group(row, "subscription-group-pnl", en("strategies.card.totalPnl"));
    expect(await within(pnl).findByText(usdt(67.2, true))).toBeInTheDocument();
    expect(within(pnl).getByTestId("subscription-return")).toHaveTextContent(pct(0.109));

    const drawdown = group(row, "subscription-group-drawdown", en("strategies.card.maxDrawdown"));
    expect(within(drawdown).getByTestId("subscription-deepest")).toHaveTextContent(pct(-0.0971));

    const profitable = group(row, "subscription-group-profitable", en("strategies.card.profitableTrades"));
    expect(within(profitable).getByTestId("subscription-winrate")).toHaveTextContent("66.7%");
    expect(within(profitable).getByTestId("subscription-wins")).toHaveTextContent("4/6");

    const aum = group(row, "subscription-group-aum", en("strategies.card.aum"));
    expect(within(aum).getByTestId("subscription-subscribers")).toHaveTextContent(/^2$/);
    expect(within(aum).getByTestId("subscription-capital")).toHaveTextContent(usdt(1500));

    const setup = group(row, "subscription-group-setup", en("strategies.card.setup"));
    expect(within(setup).getByTestId("subscription-share")).toHaveTextContent("30%");
    expect(within(setup).getByTestId("subscription-leverage")).toHaveTextContent("x1");

    expect(within(row).queryByTestId("subscription-uptime")).toBeNull();
    expect(within(row).queryByTestId("subscription-trades")).toBeNull();
  });
});

describe("a card on My strategies", () => {
  it("joins the author's PnL and return under Total PnL and draws no settings", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    expect(within(row).getByTestId("strategy-age")).toHaveTextContent("Sep 1, 2026 – Nov 17, 2026");

    const pnl = group(row, "strategy-group-pnl", en("strategies.card.totalPnl"));
    expect(await within(pnl).findByText(usdt(67.2, true))).toBeInTheDocument();
    expect(within(pnl).getByTestId("strategy-return")).toHaveTextContent(pct(0.109));

    const profitable = group(row, "strategy-group-profitable", en("strategies.card.profitableTrades"));
    expect(within(profitable).getByTestId("strategy-wins")).toHaveTextContent("4/6");

    const aum = group(row, "strategy-group-aum", en("strategies.card.aum"));
    expect(within(aum).getByTestId("strategy-capital")).toHaveTextContent(usdt(1500));

    expect(within(row).queryByTestId("strategy-group-setup")).toBeNull();
    expect(within(row).queryByTestId("strategy-uptime")).toBeNull();
  });
});
