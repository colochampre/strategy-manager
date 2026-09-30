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

export function pool(exchange: string, venue = "usdt-m", settlementCurrency = "USDT") {
  return {
    exchange,
    venue,
    settlement_currency: settlementCurrency,
    enabled: true,
    balance: null,
    reserved: "0",
    allocatable: null,
  };
}

/** One Bybit pool unless a test says otherwise, so the exchange scope is ready. */
const DEFAULT_POOLS: PoolsStub = { kind: "ok", body: [pool("bybit", "linear")] };

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response;
}

/** Routes the endpoints the shell touches; everything else is a loud failure. */
export function stubApi(
  health: HealthStub,
  bookings: unknown[] = [],
  pools: PoolsStub = DEFAULT_POOLS,
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/health")) {
      if (health.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (health.kind === "pending") return new Promise<Response>(() => undefined);
      if (health.kind === "status") return Promise.resolve(jsonResponse(health.body ?? {}, health.status));
      return Promise.resolve(jsonResponse(health.body));
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
