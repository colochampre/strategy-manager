import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchPoolPerformance, poolPerformanceKey } from "@/shared/api/performance";
import { emptyPerformance, lock, unlock } from "@/test/harness";

function respond(status: number, body: unknown) {
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

describe("fetchPoolPerformance", () => {
  it("reads the pool's report from its own path", async () => {
    const fetchMock = respond(200, emptyPerformance("bybit", "linear", "USDT"));

    const report = await fetchPoolPerformance("bybit", "linear", "USDT");

    expect(report?.currency).toBe("USDT");
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/performance\/pools\/bybit\/linear\/USDT$/);
  });

  it("escapes the path segments", async () => {
    const fetchMock = respond(200, emptyPerformance("a b", "c/d", "USDT"));

    await fetchPoolPerformance("a b", "c/d", "USDT");

    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/pools\/a%20b\/c%2Fd\/USDT$/);
  });

  it("answers null for a 404, because an unknown pool is not a failure", async () => {
    respond(404, { detail: "no such pool" });

    expect(await fetchPoolPerformance("bybit", "linear", "USDT")).toBeNull();
  });

  it.each([500, 503, 401])("rejects a %s as an ApiError", async (status) => {
    respond(status, { detail: "boom" });

    await expect(fetchPoolPerformance("bybit", "linear", "USDT")).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["a non-object", []],
    ["no curve", { ...emptyPerformance("bybit", "linear", "USDT"), curve: undefined }],
    ["no monthly", { ...emptyPerformance("bybit", "linear", "USDT"), monthly: "x" }],
    ["no ranges", { ...emptyPerformance("bybit", "linear", "USDT"), ranges: null }],
    ["no excluded", { ...emptyPerformance("bybit", "linear", "USDT"), excluded: undefined }],
    ["no max_drawdown", { ...emptyPerformance("bybit", "linear", "USDT"), max_drawdown: 0 }],
  ])("rejects a malformed body (%s) instead of reading it as an empty ledger", async (_label, body) => {
    respond(200, body);

    await expect(fetchPoolPerformance("bybit", "linear", "USDT")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("poolPerformanceKey", () => {
  it("is ['performance','pool',exchange,venue,currency]", () => {
    expect(poolPerformanceKey("bybit", "linear", "USDT")).toEqual([
      "performance",
      "pool",
      "bybit",
      "linear",
      "USDT",
    ]);
  });
});
