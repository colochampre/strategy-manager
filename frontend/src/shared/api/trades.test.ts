import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchMyTrades, myTradesKey } from "@/shared/api/trades";
import { lock, unlock } from "@/test/harness";

const ROW = {
  allocation_id: "a1",
  strategy_id: "s1",
  strategy_name: "Alpha",
  strategy_archived: false,
  strategy_page: "AUTHORED",
  exchange: "bybit",
  venue: "usdt-m",
  currency: "USDT",
  pair: "SOLUSDT",
  direction: "LONG",
  opened_at: "2026-11-01T10:00:00Z",
  closed_at: "2026-11-01T12:00:00Z",
  rehearsal: false,
  entry_price: "100",
  exit_price: "110",
  pnl: "5.5",
  fees_complete: true,
  close_cause: "SIGNAL",
};

const BODY = { trades: [ROW], total: 1, strategies: [{ id: "s1", name: "Alpha", archived: false }], exchanges: ["bybit"] };

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchMyTrades", () => {
  it("asks for the page with only the filters that are set", async () => {
    const fetchMock = respond(BODY);

    const page = await fetchMyTrades({ limit: 20, offset: 5, closedSince: "2026-10-01T00:00:00.000Z", strategyId: "s1", exchange: "bybit" });

    expect(page.total).toBe(1);
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://x");
    expect(url.pathname).toMatch(/\/performance\/trades$/);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: "20",
      offset: "5",
      closed_since: "2026-10-01T00:00:00.000Z",
      strategy_id: "s1",
      exchange: "bybit",
    });
  });

  it("sends no filter that is not set", async () => {
    const fetchMock = respond(BODY);

    await fetchMyTrades({ limit: 20, offset: 0, closedSince: null, strategyId: null, exchange: null });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://x");
    expect([...url.searchParams.keys()].sort()).toEqual(["limit", "offset"]);
  });

  it("refuses a body that is not a page, rather than read it as no trades", async () => {
    respond({ trades: [{ ...ROW, close_cause: "WHATEVER" }], total: 1, strategies: [], exchanges: [] });
    await expect(fetchMyTrades({ limit: 20, offset: 0, closedSince: null, strategyId: null, exchange: null })).rejects.toBeInstanceOf(
      ApiError,
    );

    respond({ trades: [], total: "1", strategies: [], exchanges: [] });
    await expect(fetchMyTrades({ limit: 20, offset: 0, closedSince: null, strategyId: null, exchange: null })).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("keys the cache by every parameter", () => {
    const base = { limit: 20, offset: 0, closedSince: null, strategyId: null, exchange: null };
    expect(myTradesKey(base)).not.toEqual(myTradesKey({ ...base, offset: 20 }));
    expect(myTradesKey(base)).not.toEqual(myTradesKey({ ...base, exchange: "bybit" }));
  });
});
