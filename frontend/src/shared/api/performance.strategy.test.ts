import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategyPerformance, fetchStrategyTrades } from "@/shared/api/performance";
import type { StrategyTrade } from "@/shared/api/types";
import { emptyPerformance, lock, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function report(byPair: unknown) {
  return { ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: byPair };
}

function trade(overrides: Partial<StrategyTrade> = {}): StrategyTrade {
  return {
    allocation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    pair: "SOLUSDT",
    direction: "LONG",
    opened_at: "2026-09-30T10:00:00Z",
    closed_at: "2026-09-30T12:00:00Z",
    rehearsal: false,
    rehearsal_fill_price: null,
    base_currency: "SOL",
    entry_price: "0.451200000000000000",
    exit_price: "0.463100000000000000",
    size: "1250.000000000000000000",
    fees: "0.63",
    other_fees: [],
    pnl: "4.20",
    capital_at_open: "1000.00",
    return: "0.0042000000",
    fees_complete: true,
    ...overrides,
  };
}

const CURSOR = {
  before_closed_at: "2026-09-30T12:00:00.123456Z",
  before_allocation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
};

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchStrategyPerformance by_pair", () => {
  it("returns the pairs the server listed, a null return kept as null", async () => {
    const entry = { pair: "SOLUSDT", trades: 3, wins: 2, win_rate: "0.6666666667", pnl: "4.20", return: null };
    respond(200, report([entry]));

    const body = await fetchStrategyPerformance(ID);

    expect(body?.by_pair).toEqual([entry]);
  });

  it.each([
    ["is missing", undefined],
    ["is not a list", { SOLUSDT: 1 }],
    [
      "has an entry whose pnl is a number",
      [{ pair: "SOLUSDT", trades: 3, wins: 2, win_rate: "0.6666666667", pnl: 4.2, return: null }],
    ],
    [
      "has an entry whose trade count is a string",
      [{ pair: "SOLUSDT", trades: "3", wins: 2, win_rate: "0.6666666667", pnl: "4.20", return: null }],
    ],
    ["has an entry with no pair", [{ trades: 3, wins: 2, win_rate: "0.6666666667", pnl: "4.20", return: null }]],
    [
      "has an entry whose return is a number",
      [{ pair: "SOLUSDT", trades: 3, wins: 2, win_rate: "0.6666666667", pnl: "4.20", return: 0.01 }],
    ],
  ])("rejects a body whose by_pair %s, so no wrong figure is drawn", async (_name, byPair) => {
    respond(200, report(byPair));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchStrategyTrades", () => {
  it("asks for the first page with the limit and include_rehearsal and no cursor", async () => {
    const fetchMock = respond(200, { trades: [trade()], next_cursor: null });

    const page = await fetchStrategyTrades(ID, null);

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    expect(url.pathname).toMatch(new RegExp(`/performance/strategies/${ID}/trades$`));
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("include_rehearsal")).toBe("true");
    expect(url.searchParams.has("before_closed_at")).toBe(false);
    expect(url.searchParams.has("before_allocation_id")).toBe(false);
    expect(page.trades).toEqual([trade()]);
    expect(page.next_cursor).toBeNull();
  });

  it("sends the cursor back exactly as served: both values, the instant untouched", async () => {
    const fetchMock = respond(200, { trades: [], next_cursor: null });

    await fetchStrategyTrades(ID, CURSOR);

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    expect(url.searchParams.get("before_closed_at")).toBe(CURSOR.before_closed_at);
    expect(url.searchParams.get("before_allocation_id")).toBe(CURSOR.before_allocation_id);
    expect(url.searchParams.get("limit")).toBe("20");
  });

  it("returns the cursor the server answered for the next page", async () => {
    respond(200, { trades: [trade()], next_cursor: CURSOR });

    const page = await fetchStrategyTrades(ID, null);

    expect(page.next_cursor).toEqual(CURSOR);
  });

  it("throws for a 404 rather than reading it as an empty list", async () => {
    respond(404, { detail: "no such strategy" });

    await expect(fetchStrategyTrades(ID, null)).rejects.toMatchObject({ status: 404 });
  });

  it.each([
    ["is not an object", []],
    ["has no trades list", { next_cursor: null }],
    ["has no next_cursor key", { trades: [] }],
    ["has a half cursor", { trades: [], next_cursor: { before_closed_at: "2026-09-30T12:00:00Z" } }],
    ["has a trade whose pnl is a number", { trades: [{ ...trade(), pnl: 4.2 }], next_cursor: null }],
    ["has a trade whose fees_complete is a string", { trades: [{ ...trade(), fees_complete: "false" }], next_cursor: null }],
    ["has a trade with no closed_at", { trades: [{ ...trade(), closed_at: undefined }], next_cursor: null }],
    ["has a trade whose capital_at_open is a number", { trades: [{ ...trade(), capital_at_open: 1000 }], next_cursor: null }],
    ["has a trade whose return is missing", { trades: [{ ...trade(), return: undefined }], next_cursor: null }],
  ])("rejects a body that %s", async (_name, body) => {
    respond(200, body);

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it("keeps a trade without capital at open, its return null", async () => {
    respond(200, { trades: [trade({ capital_at_open: null, return: null })], next_cursor: null });

    const page = await fetchStrategyTrades(ID, null);

    expect(page.trades[0]).toMatchObject({ capital_at_open: null, return: null });
  });
});
