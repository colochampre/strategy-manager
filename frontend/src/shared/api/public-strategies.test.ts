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
  ])("refuses %s", async (_name, body) => {
    stubFetch(jsonResponse(body));

    await expect(fetchPublicStrategies()).rejects.toBeInstanceOf(ApiError);
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
