import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchPublicRecord } from "@/shared/api/public-record";
import { jsonResponse, publicRecord } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchPublicRecord", () => {
  it("reads the record from its own route", async () => {
    const body = publicRecord();
    const fetchMock = stubFetch(jsonResponse(body));

    await expect(fetchPublicRecord(ID)).resolves.toEqual(body);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${API_BASE_URL}/api/public/strategies/${ID}/record`);
  });

  it("takes a null origin, which is a record with no closed trade", async () => {
    const body = publicRecord({ origin: null, closed_trade_count: 0, curve: [], monthly: [], by_pair: [] });
    stubFetch(jsonResponse(body));

    await expect(fetchPublicRecord(ID)).resolves.toEqual(body);
  });

  it("answers null for a strategy that is not on the public list", async () => {
    stubFetch(jsonResponse({ detail: "no such strategy" }, 404));

    await expect(fetchPublicRecord(ID)).resolves.toBeNull();
  });

  it("throws on any other failure", async () => {
    stubFetch(jsonResponse({ detail: "boom" }, 500));

    await expect(fetchPublicRecord(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["a body that is not a record", []],
    ["a numeric max drawdown", publicRecord({ max_drawdown: -0.02 })],
    ["a numeric origin", publicRecord({ origin: 20261010 })],
    ["a fractional trade count", publicRecord({ closed_trade_count: 1.5 })],
    ["a curve that is not a list", publicRecord({ curve: {} })],
    ["a curve point with a numeric index", publicRecord({ curve: [{ date: "2026-10-10", daily_return: "0", index: 0, drawdown: "0" }] })],
    ["a month with a string year", publicRecord({ monthly: [{ year: "2026", month: 10, return: "0.04" }] })],
    ["a range with a numeric return", publicRecord({ ranges: [{ range: "7D", return: 0.01, trade_count: 1 }] })],
    ["a pair with more wins than trades", publicRecord({ by_pair: [{ pair: "SOLUSDT", trades: 1, wins: 2, win_rate: "1", return: "0.04" }] })],
    ["a pair with a null return", publicRecord({ by_pair: [{ pair: "SOLUSDT", trades: 1, wins: 1, win_rate: "1", return: null }] })],
    ["a record that carries money", publicRecord({ total_pnl: "12.5" })],
  ])("refuses %s", async (_name, body) => {
    stubFetch(jsonResponse(body));

    await expect(fetchPublicRecord(ID)).rejects.toThrow(/Unexpected response shape/);
  });
});
