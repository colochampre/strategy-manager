import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { matchesName } from "@/features/strategies/StrategySearch";
import i18n from "@/shared/i18n";
import {
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

const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";

const SEARCH = () => screen.getByRole("searchbox", { name: i18n.t("strategies.search.label") });

function serveLists() {
  const publics = [
    publicStrategy({ id: ALPHA, name: "Ácido BTC 4h" }),
    publicStrategy({ id: BETA, name: "ETH mean reversion" }),
  ];
  const held = [
    heldSubscription({ strategy_name: "Ácido BTC 4h" }),
    heldSubscription({ id: "33333333-3333-4333-8333-333333333333", strategy_id: BETA, strategy_name: "ETH mean reversion" }),
  ];
  const authored = publics.map((strategy) => ({
    id: strategy.id,
    name: strategy.name,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 86_400, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 0,
    live_subscribers: 0,
    created_at: "2026-09-01T10:00:00Z",
    capital: null,
    stop_loss_pct: "10.00",
  }));
  return stubApi(
    { kind: "ok", body: { status: "ok", dry_run: true } },
    [],
    { kind: "ok", body: [pool("bybit", "usdt-m")] },
    {},
    (url) => {
      const path = new URL(url, "http://localhost").pathname;
      if (path.endsWith("/api/public/strategies")) return Promise.resolve(jsonResponse(publics));
      if (path.endsWith("/api/subscriptions/held")) return Promise.resolve(jsonResponse(held));
      if (path.endsWith("/api/strategies")) return Promise.resolve(jsonResponse(authored));
      return undefined;
    },
  );
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("matchesName", () => {
  it("matches any part of the name, ignoring case, accents and the query's outer spaces", () => {
    expect(matchesName("Ácido BTC 4h", "  acido ")).toBe(true);
    expect(matchesName("Ácido BTC 4h", "btc 4H")).toBe(true);
    expect(matchesName("Ácido BTC 4h", "eth")).toBe(false);
  });

  it("lets every name through an empty query", () => {
    expect(matchesName("Ácido BTC 4h", "")).toBe(true);
    expect(matchesName("Ácido BTC 4h", "   ")).toBe(true);
  });
});

describe.each([
  ["My subscriptions", "/strategies", "subscription-row", null],
  ["Explore", "/strategies/explore", "public-strategy-row", "strategies.entry.haveCode"],
  ["My strategies", "/strategies/authored", "strategy-row", "strategies.new.open"],
] as const)("the name search on %s", (_list, path, rowTestId, buttonKey) => {
  it("keeps only the strategies whose name matches, and says so when none does", async () => {
    serveLists();
    renderAt(<AppRoutes />, path);
    expect(await screen.findAllByTestId(rowTestId)).toHaveLength(2);

    fireEvent.change(SEARCH(), { target: { value: "acido" } });
    const rows = screen.getAllByTestId(rowTestId);
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "Ácido BTC 4h" })).toBeInTheDocument();

    fireEvent.change(SEARCH(), { target: { value: "solana" } });
    expect(screen.queryAllByTestId(rowTestId)).toHaveLength(0);
    expect(screen.getByText(i18n.t("strategies.search.noMatch", { query: "solana" }))).toBeInTheDocument();

    fireEvent.change(SEARCH(), { target: { value: "" } });
    expect(screen.getAllByTestId(rowTestId)).toHaveLength(2);
  });

  it("sits in one toolbar row with the list's button, as tall as that button", async () => {
    serveLists();
    renderAt(<AppRoutes />, path);
    await screen.findAllByTestId(rowTestId);

    const toolbar = screen.getByTestId("list-toolbar");
    expect(within(toolbar).getByRole("searchbox")).toBe(SEARCH());
    expect(SEARCH()).toHaveClass("min-h-11");
    // One row from sm up; on a phone the search takes its own full-width row above the buttons.
    expect(toolbar).toHaveClass("flex-col", "sm:flex-row");
    if (buttonKey !== null) {
      expect(within(toolbar).getByRole("button", { name: i18n.t(buttonKey) })).toHaveClass("min-h-11");
    }
  });
});
