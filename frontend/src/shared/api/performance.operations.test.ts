import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategyTrades } from "@/shared/api/performance";
import type { StrategyTrade } from "@/shared/api/types";
import { lock, unlock } from "@/test/harness";

// Decision 43: the fields a row of the trades list carries beyond the original nine, and the
// opt-in that asks for rehearsal rows. A page that lacks them is refused whole, so no row is
// drawn with an invented figure.

const ID = "11111111-1111-4111-8111-111111111111";

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function trade(overrides: Partial<StrategyTrade> = {}): StrategyTrade {
  return {
    allocation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    pair: "STXUSDT",
    direction: "LONG",
    opened_at: "2026-09-30T10:00:00Z",
    closed_at: "2026-09-30T12:00:00Z",
    rehearsal: false,
    rehearsal_fill_price: null,
    base_currency: "STX",
    entry_price: "0.451200000000000000",
    exit_price: "0.463100000000000000",
    size: "1250.000000000000000000",
    fees: "0.63",
    other_fees: [],
    pnl: "14.245000000000000000",
    capital_at_open: "1000.00",
    return: "0.0142450000",
    fees_complete: true,
    ...overrides,
  };
}

function page(row: unknown) {
  return { trades: [row], next_cursor: null };
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

describe("a page of the trades list under decision 43", () => {
  it.each([
    "rehearsal",
    "rehearsal_fill_price",
    "fees",
    "other_fees",
    "entry_price",
    "exit_price",
    "size",
    "base_currency",
  ])("refuses a page whose row lacks %s", async (field) => {
    const row: Record<string, unknown> = { ...trade() };
    delete row[field];
    respond(200, page(row));

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["fees", { fees: 0.63 }],
    ["size", { size: 1250 }],
    ["entry_price", { entry_price: 0.4512 }],
    ["exit_price", { exit_price: 0.4631 }],
    ["base_currency", { base_currency: 7 }],
    ["an other_fees amount", { other_fees: [{ currency: "BNB", amount: 0.00012 }] }],
  ])("refuses a number where a string is due: %s", async (_name, overrides) => {
    respond(200, page({ ...trade(), ...overrides }));

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a rehearsal row whose rehearsal_fill_price is null", async () => {
    respond(200, page(trade({ rehearsal: true, rehearsal_fill_price: null })));

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a real row whose rehearsal_fill_price is set", async () => {
    respond(200, page(trade({ rehearsal: false, rehearsal_fill_price: "FIXED_ONE" })));

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a page of the original nine fields", async () => {
    respond(
      200,
      page({
        allocation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        pair: "STXUSDT",
        direction: "LONG",
        opened_at: "2026-09-30T10:00:00Z",
        closed_at: "2026-09-30T12:00:00Z",
        pnl: "14.245",
        capital_at_open: "1000.00",
        return: "0.0142450000",
        fees_complete: true,
      }),
    );

    await expect(fetchStrategyTrades(ID, null)).rejects.toBeInstanceOf(ApiError);
  });

  it("accepts a rehearsal row whose rehearsal_fill_price is a value the panel does not know", async () => {
    respond(200, page(trade({ rehearsal: true, rehearsal_fill_price: "SLIPPED" })));

    const result = await fetchStrategyTrades(ID, null);

    expect(result.trades[0]?.rehearsal_fill_price).toBe("SLIPPED");
  });

  it("accepts a row whose four figures are all null", async () => {
    const row = trade({ base_currency: null, entry_price: null, exit_price: null, size: null });
    respond(200, page(row));

    const result = await fetchStrategyTrades(ID, null);

    expect(result.trades).toEqual([row]);
  });

  it("sends include_rehearsal=true on the first page and on every later page, with the limit and the cursor", async () => {
    const fetchMock = respond(200, { trades: [], next_cursor: null });

    await fetchStrategyTrades(ID, null);
    await fetchStrategyTrades(ID, CURSOR);

    const first = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    const later = new URL(String(fetchMock.mock.calls[1]?.[0]), "http://localhost");
    expect(first.searchParams.get("include_rehearsal")).toBe("true");
    expect(first.searchParams.get("limit")).toBe("20");
    expect(first.searchParams.has("before_closed_at")).toBe(false);
    expect(later.searchParams.get("include_rehearsal")).toBe("true");
    expect(later.searchParams.get("limit")).toBe("20");
    expect(later.searchParams.get("before_closed_at")).toBe(CURSOR.before_closed_at);
    expect(later.searchParams.get("before_allocation_id")).toBe(CURSOR.before_allocation_id);
  });
});
