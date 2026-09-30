import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const TWO_EXCHANGES = { kind: "ok", body: [pool("bybit", "linear"), pool("binance")] } as const;

function proposal(exchange: string, symbol: string) {
  return {
    id: `id-${symbol}`,
    discrepancy_id: "d",
    exchange,
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol,
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    allocation_id: "a",
    strategy_id: "s",
    side: "SELL",
    quantity: "1",
    observed_venue_net_base: "0",
    observed_ledger_net_base: "-1",
    observed_allocation_ids: [],
    fills: [],
    client_order_id: "c",
    expires_at: "2026-09-24T01:02:03+00:00",
    prepared_by_job_id: "j",
    created_at: "2026-09-23T01:02:03+00:00",
    state: "PENDING",
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    execution_attempt_id: null,
  };
}

const BOOKINGS = [proposal("bybit", "SOLUSDT.P"), proposal("binance", "ETHUSDT.P")];

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("decision rail scoped to the exchange", () => {
  it("shows only the default exchange's pending bookings at first", async () => {
    stubApi(HEALTH, BOOKINGS, TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByText("SOLUSDT.P")).toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
  });

  it("switches the rail to the other exchange when its tab is clicked", async () => {
    stubApi(HEALTH, BOOKINGS, TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findByText("SOLUSDT.P");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    expect(await screen.findByText("ETHUSDT.P")).toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
  });

  it("shows the empty state for an exchange with nothing pending", async () => {
    stubApi(HEALTH, [proposal("bybit", "SOLUSDT.P")], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findByText("SOLUSDT.P");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    expect(await screen.findByText(en.bookings.empty)).toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
  });
});

describe("while the exchange scope is not known", () => {
  it("shows no bookings while pools load", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "pending" });
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    expect(rail).toHaveTextContent(en.overview.decisionRail.scopeLoading);
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText(en.bookings.empty)).not.toBeInTheDocument();
  });

  it.each([
    ["a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["a network failure", { kind: "network-error" }],
    ["a malformed body", { kind: "ok", body: { items: [] } }],
  ] as const)("never shows unfiltered bookings when pools fail with %s", async (_label, stub) => {
    stubApi(HEALTH, BOOKINGS, stub);
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.scopeError));
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText(en.bookings.empty)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: en.bookings.actions.approve })).not.toBeInTheDocument();
  });

  it("says no exchange is configured, and shows no bookings, when there are no pools", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "ok", body: [] });
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.noExchanges));
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
  });

  it("keeps the rail heading and the page title in every state", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "network-error" });
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.overview.decisionRail.title })).toBeInTheDocument();
  });
});

describe("copy", () => {
  it("has the rail's scope messages in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.overview.decisionRail.scopeLoading).toBeTruthy();
      expect(locale.overview.decisionRail.scopeError).toBeTruthy();
      expect(locale.overview.decisionRail.noExchanges).toBeTruthy();
    }
  });
});
