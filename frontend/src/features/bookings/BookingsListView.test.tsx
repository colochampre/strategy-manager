import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BookingsListView } from "@/features/bookings/BookingsListView";
import { TokenGate } from "@/shared/auth/TokenGate";
import { useTokenStore } from "@/shared/auth/token-store";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function fakeResponse(body: unknown, status: number, ok: boolean = status >= 200 && status < 300): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const PROPOSAL = {
  id: "11111111-1111-1111-1111-111111111111",
  discrepancy_id: "22222222-2222-2222-2222-222222222222",
  exchange: "bybit",
  venue: "usdt-m",
  settlement_currency: "USDT",
  symbol: "STXUSDT.P",
  kind: "ATTRIBUTABLE_FULL_CLOSE",
  allocation_id: "33333333-3333-3333-3333-333333333333",
  strategy_id: "44444444-4444-4444-4444-444444444444",
  side: "SELL",
  quantity: "0.100000000000000001",
  observed_venue_net_base: "0",
  observed_ledger_net_base: "-0.1",
  observed_allocation_ids: ["33333333-3333-3333-3333-333333333333"],
  fills: [
    {
      exchange_fill_id: "fill-1",
      exchange_order_id: "order-1",
      side: "SELL",
      quantity: "0.100000000000000001",
      price: "142.37",
      fee: "0.03913",
      fee_currency: "USDT",
      filled_at: "2026-09-23T01:02:03.456000+00:00",
    },
  ],
  client_order_id: "vnu:bybit:order-1",
  expires_at: "2026-09-24T01:02:03+00:00",
  prepared_by_job_id: "55555555-5555-5555-5555-555555555555",
  created_at: "2026-09-23T01:02:03+00:00",
  state: "PENDING",
  decided_at: null,
  decided_by: null,
  decision_reason: null,
  execution_attempt_id: null,
};

describe("BookingsListView", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useTokenStore.setState({ token: "a-token" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("carries the new copy in both locales, never hardcoded", () => {
    expect(en.nav?.bookings).toBeTruthy();
    expect(en.bookings?.empty).toBeTruthy();
    expect(en.bookings?.loading).toBeTruthy();
    expect(en.bookings?.error?.title).toBeTruthy();
    expect(es.nav?.bookings).toBeTruthy();
    expect(es.bookings?.empty).toBeTruthy();
    expect(es.bookings?.loading).toBeTruthy();
    expect(es.bookings?.error?.title).toBeTruthy();
  });

  it("shows a loading state before the list resolves", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {})),
    );

    renderWithQueryClient(<BookingsListView />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the pending list from the frozen snapshot, with every fill and the exact money strings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([PROPOSAL], 200)));

    renderWithQueryClient(<BookingsListView />);

    expect(await screen.findByText("STXUSDT.P")).toBeInTheDocument();
    expect(screen.getByText("bybit", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("usdt-m", { exact: false })).toBeInTheDocument();

    // Money is never reformatted -- 18 fractional digits are rendered exactly,
    // never rounded by Number()/parseFloat()/toFixed().
    expect(screen.getAllByText("0.100000000000000001").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("142.37", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("0.03913", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("#fill-1")).toBeInTheDocument();

    // Every date carries an explicit timezone indication.
    expect(screen.getAllByText(/UTC/).length).toBeGreaterThanOrEqual(2);
  });

  it("shows the empty state when no proposals are pending, never the error state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([], 200)));

    renderWithQueryClient(<BookingsListView />);

    expect(await screen.findByText(en.bookings.empty)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error state, never the empty state, on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQueryClient(<BookingsListView />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(en.bookings.empty)).not.toBeInTheDocument();
  });

  it("shows an error state carrying the response status and detail on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse({ detail: "boom" }, 500, false)));

    renderWithQueryClient(<BookingsListView />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("500");
    expect(alert).toHaveTextContent("boom");
    expect(screen.queryByText(en.bookings.empty)).not.toBeInTheDocument();
  });

  it("returns to the TokenGate paste-once form on a 401, never showing empty or error content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ detail: "Not authenticated" }, 401, false)),
    );

    renderWithQueryClient(
      <TokenGate>
        <BookingsListView />
      </TokenGate>,
    );

    expect(await screen.findByRole("button", { name: en.auth.tokenGate.submit })).toBeInTheDocument();
    expect(screen.queryByText(en.bookings.empty)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(useTokenStore.getState().token).toBeNull();
  });
});
