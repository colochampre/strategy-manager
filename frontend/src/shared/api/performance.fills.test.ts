import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchOperationFills, useOperationFills } from "@/shared/api/performance";
import type { OperationFill } from "@/shared/api/types";
import { lock, unlock } from "@/test/harness";

// `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills` (decision 43, design § D):
// no field is nullable, the list is never empty, and a body that fails a check is an error and
// never a partial table.

const ID = "11111111-1111-4111-8111-111111111111";
const ALLOCATION = "0b6f0000-0000-4000-8000-000000000001";
const OTHER_ALLOCATION = "0b6f0000-0000-4000-8000-000000000002";

function fill(overrides: Partial<OperationFill> = {}): OperationFill {
  return {
    filled_at: "2026-09-30T12:00:00.123456Z",
    side: "BUY",
    price: "0.451200000000000000",
    quantity: "1250.000000000000000000",
    fee: "0.310000000000000000",
    fee_currency: "USDT",
    rehearsal: false,
    ...overrides,
  };
}

function body(overrides: Record<string, unknown> = {}) {
  return {
    allocation_id: ALLOCATION,
    fills: [fill(), fill({ side: "SELL", price: "0.463100000000000000", filled_at: "2026-09-30T14:30:00Z" })],
    truncated: false,
    ...overrides,
  };
}

function respond(status: number, answer: unknown) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(answer) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchOperationFills", () => {
  it("requests GET /performance/strategies/{id}/trades/{allocationId}/fills", async () => {
    const fetchMock = respond(200, body());

    await fetchOperationFills(ID, ALLOCATION);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${API_BASE_URL}/api/performance/strategies/${ID}/trades/${ALLOCATION}/fills`,
    );
  });

  it("returns the fills in the order the server served them", async () => {
    const answer = body();
    respond(200, answer);

    const result = await fetchOperationFills(ID, ALLOCATION);

    expect(result).toEqual(answer);
  });

  it("refuses a body that names another allocation than the one asked for", async () => {
    respond(200, body({ allocation_id: OTHER_ALLOCATION }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses an empty list", async () => {
    respond(200, body({ fills: [] }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a side of HOLD", async () => {
    respond(200, body({ fills: [fill({ side: "HOLD" as OperationFill["side"] })] }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["price", { price: 0.4512 }],
    ["filled_at", { filled_at: 1759233600 }],
    ["quantity", { quantity: 1250 }],
    ["fee", { fee: 0.31 }],
    ["fee_currency", { fee_currency: null }],
    ["rehearsal", { rehearsal: "false" }],
  ])("refuses a fill whose %s is of the wrong type", async (_name, overrides) => {
    respond(200, body({ fills: [{ ...fill(), ...overrides }] }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a fill that lacks a field", async () => {
    const incomplete: Record<string, unknown> = { ...fill() };
    delete incomplete.fee_currency;
    respond(200, body({ fills: [incomplete] }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a truncated that is not a boolean", async () => {
    respond(200, body({ truncated: "true" }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses one bad fill among good ones, whole", async () => {
    respond(200, body({ fills: [fill(), fill({ price: 1 as unknown as string })] }));

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toBeInstanceOf(ApiError);
  });

  it("keeps truncated", async () => {
    respond(200, body({ truncated: true }));

    const result = await fetchOperationFills(ID, ALLOCATION);

    expect(result.truncated).toBe(true);
  });

  it("throws on a 404", async () => {
    respond(404, { detail: "no such operation" });

    await expect(fetchOperationFills(ID, ALLOCATION)).rejects.toMatchObject({ status: 404 });
  });
});

describe("useOperationFills", () => {
  it("uses the query key ['performance','strategy',id,'trade-fills',allocationId]", () => {
    respond(200, body());
    const { client, wrapper } = clientWrapper();

    renderHook(() => useOperationFills(ID, ALLOCATION), { wrapper });

    const keys = client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey);
    expect(keys).toEqual([["performance", "strategy", ID, "trade-fills", ALLOCATION]]);
  });

  it("makes no request until the hook is mounted with both ids", () => {
    const fetchMock = respond(200, body());
    const { wrapper } = clientWrapper();

    // Nothing is mounted yet.
    expect(fetchMock).not.toHaveBeenCalled();

    renderHook(() => useOperationFills("", ALLOCATION), { wrapper });
    renderHook(() => useOperationFills(ID, ""), { wrapper });

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
