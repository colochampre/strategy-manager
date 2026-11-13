import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchPublicStrategies, fetchPublicStrategy } from "@/shared/api/public-strategies";
import { jsonResponse, publicStrategy } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchPublicStrategies", () => {
  it("reads the public list from its own route", async () => {
    const row = publicStrategy({ id: ID });
    const fetchMock = stubFetch(jsonResponse([row]));

    await expect(fetchPublicStrategies()).resolves.toEqual([row]);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${API_BASE_URL}/api/public/strategies`);
  });

  it("takes a null capital, which is the brake and not a fault", async () => {
    const row = publicStrategy({ capital: null });
    stubFetch(jsonResponse([row]));

    await expect(fetchPublicStrategies()).resolves.toEqual([row]);
  });

  it.each([
    ["a body that is not a list", { rows: [] }],
    ["a row with a numeric return", [publicStrategy({ unleveraged_return_before_fees: 0.1 })]],
    ["a row with a numeric capital", [publicStrategy({ capital: 100 })]],
    ["a row with a fractional live count", [publicStrategy({ live_subscribers: 1.5 })]],
    ["a row with a negative closed count", [publicStrategy({ closed_trade_count: -1 })]],
    ["a row with no author", [publicStrategy({ author_name: null })]],
    ["a row with no date", [publicStrategy({ created_at: null })]],
    ["a row with no stop level", [publicStrategy({ stop_loss_pct: undefined })]],
    ["a row with a numeric stop level", [publicStrategy({ stop_loss_pct: 10 })]],
  ])("refuses %s", async (_name, body) => {
    stubFetch(jsonResponse(body));

    await expect(fetchPublicStrategies()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("the figures the cards add to a public strategy", () => {
  it("carries the subscribers, the deepest fall, the win rate, whether it runs and its uptime", async () => {
    const row = publicStrategy({ win_rate: null, enabled: false });
    stubFetch(jsonResponse([row]));

    await expect(fetchPublicStrategies()).resolves.toMatchObject([
      { subscribers: 3, max_drawdown: "-0.05", win_rate: null, enabled: false, uptime: { baseline: false } },
    ]);
  });

  it.each([
    ["a subscriber count that is missing", { subscribers: undefined }],
    ["a subscriber count that is fractional", { subscribers: 1.5 }],
    ["a deepest fall that is a number", { max_drawdown: -0.05 }],
    ["a deepest fall that is missing", { max_drawdown: undefined }],
    ["a win rate that is a number", { win_rate: 0.6 }],
    ["a win rate that is missing", { win_rate: undefined }],
    ["an enabled flag that is a string", { enabled: "yes" }],
    ["an enabled flag that is missing", { enabled: undefined }],
    ["an uptime that is missing", { uptime: undefined }],
    ["an uptime with no baseline flag", { uptime: { seconds: 5, first_enabled_at: null } }],
    ["an uptime with a numeric first date", { uptime: { seconds: 5, first_enabled_at: 7, baseline: false } }],
  ])("refuses a list with %s", async (_name, overrides) => {
    stubFetch(jsonResponse([publicStrategy(overrides)]));

    await expect(fetchPublicStrategies()).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a single strategy with a win rate that is not a string or null", async () => {
    stubFetch(jsonResponse(publicStrategy({ id: ID, win_rate: 1 })));

    await expect(fetchPublicStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchPublicStrategy", () => {
  it("reads one strategy by its escaped id", async () => {
    const row = publicStrategy({ id: ID });
    const fetchMock = stubFetch(jsonResponse(row));

    await expect(fetchPublicStrategy(ID)).resolves.toEqual(row);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${API_BASE_URL}/api/public/strategies/${ID}`);
  });

  it("refuses a body that is not a strategy", async () => {
    stubFetch(jsonResponse({ id: ID }));

    await expect(fetchPublicStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("carries a 404, which the page reads as off the list", async () => {
    stubFetch(jsonResponse({ detail: "no such strategy" }, 404));

    await expect(fetchPublicStrategy(ID)).rejects.toMatchObject({ status: 404 });
  });
});
