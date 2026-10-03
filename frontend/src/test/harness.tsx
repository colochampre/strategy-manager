import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { useTokenStore } from "@/shared/auth/token-store";
import { useExchangeStore } from "@/shared/scope/exchange-store";

export type HealthStub =
  | { kind: "ok"; body: unknown }
  | { kind: "status"; status: number; body?: unknown }
  | { kind: "network-error" }
  | { kind: "pending" };

export type PoolsStub =
  | { kind: "ok"; body: unknown }
  | { kind: "status"; status: number; body?: unknown }
  | { kind: "network-error" }
  | { kind: "pending" };

export type PerformanceStub = PoolsStub;
export type AvailablePairsStub = PoolsStub;

/** What `GET /pools/{exchange}/{venue}/{ccy}/available-pairs` answers for a pool, in the API's shape. */
export function availablePairs(exchange: string, venue: string, currency: string, pairs: readonly string[]) {
  return {
    pool: { exchange, venue, settlement_currency: currency },
    pairs: [...pairs],
    count: pairs.length,
  };
}

export function pool(
  exchange: string,
  venue = "usdt-m",
  settlementCurrency = "USDT",
  balance: { total: string; available: string; observed_at: string; stale: boolean } | null = null,
) {
  return {
    exchange,
    venue,
    settlement_currency: settlementCurrency,
    enabled: true,
    balance,
    reserved: "0",
    allocatable: balance === null ? null : balance.available,
  };
}

/** What `GET /performance/pools/...` answers for a pool with an empty ledger (the DRY_RUN reality). */
export function emptyPerformance(exchange: string, venue: string, currency: string) {
  return {
    pool: { exchange, venue, settlement_currency: currency },
    currency,
    day_boundary: "UTC",
    trade_count: 0,
    total_pnl: "0",
    max_drawdown: "0.0000000000",
    excluded: {
      open_trade_count: 0,
      rehearsal_fill_count: 0,
      no_capital_at_open: 0,
      unconverted_fee: 0,
      unresolved_allocation_count: 0,
    },
    ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({
      range,
      pnl: "0",
      return: "0.0000000000",
      trade_count: 0,
    })),
    curve: [],
    monthly: [],
  };
}

/**
 * An `ExtraRoute` that serves one strategy's detail and its empty enable
 * history, so a deep link to its page can load. Pass it as `stubApi`'s `extra`.
 */
export function strategyRoute(id: string, name: string): ExtraRoute {
  const detail = {
    id,
    name,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
  };
  return (url) => {
    if (url.endsWith(`/strategies/${id}/events`)) return Promise.resolve(jsonResponse([]));
    if (url.endsWith(`/strategies/${id}`)) return Promise.resolve(jsonResponse(detail));
    return undefined;
  };
}

/** One Bybit pool unless a test says otherwise, so the exchange scope is ready. */
const DEFAULT_POOLS: PoolsStub = { kind: "ok", body: [pool("bybit", "usdt-m")] };

/** The venue's spelling (`STXUSDT`), sorted, as the endpoint answers it; a pool without an entry gets these. */
const DEFAULT_AVAILABLE_PAIRS = ["AAVEUSDT", "SFPUSDT", "STXUSDT"] as const;

export function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response;
}

/**
 * Answers a request a view of its own owns (the strategies endpoints, say), or
 * returns `undefined` to leave it to the shell's routes.
 */
export type ExtraRoute = (url: string, init?: RequestInit) => Promise<Response> | undefined;

/**
 * Routes the endpoints the shell touches; everything else is a loud failure.
 * `performance` overrides a pool's report, keyed `exchange/venue/ccy`; a pool
 * without an entry answers an empty ledger. `extra` is asked first. `available`
 * overrides a pool's available pairs, keyed `exchange/venue/ccy`; a pool without
 * an entry lists `AAVEUSDT`, `SFPUSDT` and `STXUSDT`.
 */
export function stubApi(
  health: HealthStub,
  bookings: unknown[] = [],
  pools: PoolsStub = DEFAULT_POOLS,
  performance: Record<string, PerformanceStub> = {},
  extra?: ExtraRoute,
  available: Record<string, AvailablePairsStub> = {},
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const owned = extra?.(url, init);
    if (owned !== undefined) return owned;
    if (url.endsWith("/health")) {
      if (health.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (health.kind === "pending") return new Promise<Response>(() => undefined);
      if (health.kind === "status") return Promise.resolve(jsonResponse(health.body ?? {}, health.status));
      return Promise.resolve(jsonResponse(health.body));
    }
    const performancePath = /\/performance\/pools\/(.+)$/.exec(url);
    if (performancePath) {
      const key = decodeURIComponent(performancePath[1] ?? "");
      const [exchange = "", venue = "", currency = ""] = key.split("/");
      const stub: PerformanceStub = performance[key] ?? {
        kind: "ok",
        body: emptyPerformance(exchange, venue, currency),
      };
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    const pairsPath = /\/pools\/([^/]+)\/([^/]+)\/([^/]+)\/available-pairs$/.exec(url);
    if (pairsPath) {
      const [exchange = "", venue = "", currency = ""] = pairsPath.slice(1).map((part) => decodeURIComponent(part ?? ""));
      const stub: AvailablePairsStub = available[`${exchange}/${venue}/${currency}`] ?? {
        kind: "ok",
        body: availablePairs(exchange, venue, currency, DEFAULT_AVAILABLE_PAIRS),
      };
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    if (url.endsWith("/pools")) {
      if (pools.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (pools.kind === "pending") return new Promise<Response>(() => undefined);
      if (pools.kind === "status") return Promise.resolve(jsonResponse(pools.body ?? {}, pools.status));
      return Promise.resolve(jsonResponse(pools.body));
    }
    if (url.includes("/reconciliation/bookings")) return Promise.resolve(jsonResponse(bookings));
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * jsdom has no layout, so the `lg` breakpoint (1024 px) is a stubbed
 * `matchMedia`: `wide` matches `(min-width: 1024px)`, `narrow` does not.
 * `vi.unstubAllGlobals()` in `afterEach` puts it back.
 */
export function setViewport(width: "wide" | "narrow"): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width === "wide",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

export function unlock(): void {
  useTokenStore.setState({ token: "test-token" });
}

export function lock(): void {
  window.localStorage.clear();
  useTokenStore.setState({ token: null });
}

/** Forget the exchange picked in an earlier test, in memory and in storage. */
export function resetExchangeScope(): void {
  window.localStorage.clear();
  useExchangeStore.setState({ selected: null });
}

export function renderAt(ui: ReactElement, path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
