import { describe, expect, it } from "vitest";

import type { CredentialEntry } from "@/shared/api/credentials";
import type { Strategy, HeldSubscription } from "@/shared/api/types";
import { runningExchanges, type RunningSources } from "@/shared/scope/running-exchanges";
import { emptyKey, heldSubscription, openPosition, openState, pool, storedKey } from "@/test/harness";

const POOLS = [pool("bybit"), pool("binance"), pool("pionex"), pool("bybit", "spot")];

function strategy(exchange: string, overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Beta",
    exchange,
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: [],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    secret_last4: "x4F2",
    description: null,
    subscribers: 0,
    live_subscribers: 0,
    capital: null,
    ...overrides,
  };
}

function held(exchange: string, status: string): HeldSubscription {
  return heldSubscription({ exchange, status }) as unknown as HeldSubscription;
}

function keys(...rows: unknown[]): CredentialEntry[] {
  return rows as CredentialEntry[];
}

/** Every source answered and nothing runs, so a test adds the one thing it is about. */
function sources(overrides: Partial<RunningSources> = {}): RunningSources {
  return {
    pools: POOLS,
    credentials: [],
    positions: openState(),
    strategies: [],
    subscriptions: [],
    ...overrides,
  };
}

describe("what makes a tab", () => {
  it("shows an exchange with an active key", () => {
    const result = runningExchanges(sources({ credentials: keys(storedKey("binance"), emptyKey("bybit")) }));

    expect(result).toEqual(["binance"]);
  });

  it("shows an exchange with an open position, without any key", () => {
    const position = openPosition({ pool: { exchange: "pionex", venue: "usdt-m", settlement_currency: "USDT" } });

    expect(runningExchanges(sources({ positions: openState([position]) }))).toEqual(["pionex"]);
  });

  it("shows an exchange with an enabled strategy that is not archived", () => {
    expect(runningExchanges(sources({ strategies: [strategy("binance")] }))).toEqual(["binance"]);
  });

  it("shows an exchange with an ACTIVE subscription", () => {
    expect(runningExchanges(sources({ subscriptions: [held("pionex", "ACTIVE")] }))).toEqual(["pionex"]);
  });

  it("shows no tab for an exchange that only has pools", () => {
    const result = runningExchanges(sources({ credentials: keys(storedKey("binance")) }));

    expect(result).not.toContain("bybit");
    expect(result).not.toContain("pionex");
  });

  it("shows no tab for a disabled strategy, an archived one, or an ended or leaving subscription", () => {
    const result = runningExchanges(
      sources({
        credentials: keys(storedKey("binance")),
        strategies: [
          strategy("bybit", { enabled: false }),
          strategy("pionex", { archived_at: "2026-11-01T00:00:00Z" }),
        ],
        subscriptions: [held("bybit", "ENDED"), held("pionex", "LEAVING")],
      }),
    );

    expect(result).toEqual(["binance"]);
  });

  it("keeps the order the pools list them in, whatever order the sources name them", () => {
    const result = runningExchanges(
      sources({
        credentials: keys(storedKey("pionex")),
        strategies: [strategy("binance")],
        subscriptions: [held("bybit", "ACTIVE")],
      }),
    );

    expect(result).toEqual(["bybit", "binance", "pionex"]);
  });

  it("lists an exchange once however many things run on it", () => {
    const result = runningExchanges(
      sources({
        credentials: keys(storedKey("bybit")),
        strategies: [strategy("bybit")],
        subscriptions: [held("bybit", "ACTIVE")],
        positions: openState([openPosition()]),
      }),
    );

    expect(result).toEqual(["bybit"]);
  });
});

describe("when the rule cannot answer", () => {
  const RUNNING = { credentials: keys(storedKey("binance")) };

  it.each([
    ["credentials", { credentials: undefined }],
    ["positions", { positions: undefined }],
    ["strategies", { strategies: undefined }],
    ["subscriptions", { subscriptions: undefined }],
  ])("keeps every pool exchange while %s has not answered", (_name, unanswered) => {
    const result = runningExchanges(sources({ ...RUNNING, ...unanswered }));

    expect(result).toEqual(["bybit", "binance", "pionex"]);
  });

  it("falls back to the pool exchanges when every source answered and nothing runs", () => {
    expect(runningExchanges(sources())).toEqual(["bybit", "binance", "pionex"]);
  });

  it("has no exchange when there are no pools", () => {
    expect(runningExchanges(sources({ pools: [], credentials: keys(storedKey("bybit")) }))).toEqual([]);
  });
});
