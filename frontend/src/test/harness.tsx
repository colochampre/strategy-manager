import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { useTokenStore } from "@/shared/auth/token-store";

export type HealthStub =
  | { kind: "ok"; body: unknown }
  | { kind: "status"; status: number; body?: unknown }
  | { kind: "network-error" }
  | { kind: "pending" };

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response;
}

/** Routes the two endpoints the shell touches; everything else is a loud failure. */
export function stubApi(health: HealthStub, bookings: unknown[] = []) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/health")) {
      if (health.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (health.kind === "pending") return new Promise<Response>(() => undefined);
      if (health.kind === "status") return Promise.resolve(jsonResponse(health.body ?? {}, health.status));
      return Promise.resolve(jsonResponse(health.body));
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

export function renderAt(ui: ReactElement, path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
