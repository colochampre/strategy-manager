import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchAvailablePairs, useAvailablePairs } from "@/shared/api/pairs";
import type { PoolKey } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

const BYBIT: PoolKey = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };
const BINANCE: PoolKey = { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" };

function body(pool: PoolKey, pairs: string[]) {
  return { pool, pairs, count: pairs.length };
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
}

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
});

describe("fetchAvailablePairs", () => {
  it("requests /api/pools/{exchange}/{venue}/{ccy}/available-pairs for the chosen pool", async () => {
    const fetchMock = stubFetch(jsonResponse(body(BINANCE, ["AAVEUSDT", "STXUSDT"])));

    const result = await fetchAvailablePairs(BINANCE);

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/pools/binance/usdt-m/USDT/available-pairs`);
    expect(result).toEqual(body(BINANCE, ["AAVEUSDT", "STXUSDT"]));
  });

  it("encodes each path segment so a value can never add a segment", async () => {
    const odd: PoolKey = { exchange: "by/bit", venue: "usdt-m", settlement_currency: "U SD" };
    const fetchMock = stubFetch(jsonResponse(body(odd, [])));

    await fetchAvailablePairs(odd);

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/pools/by%2Fbit/usdt-m/U%20SD/available-pairs`);
  });

  it("accepts a well-formed empty list as a list, not as an error", async () => {
    stubFetch(jsonResponse(body(BYBIT, [])));

    await expect(fetchAvailablePairs(BYBIT)).resolves.toEqual({ pool: BYBIT, pairs: [], count: 0 });
  });

  it.each([
    ["pairs is missing", { pool: BYBIT, count: 0 }],
    ["pairs is not an array", { pool: BYBIT, pairs: "STXUSDT", count: 1 }],
    ["pairs holds a non-string", { pool: BYBIT, pairs: ["STXUSDT", 7], count: 2 }],
    ["count disagrees with the list", { pool: BYBIT, pairs: ["STXUSDT"], count: 2 }],
    ["pool is missing", { pairs: ["STXUSDT"], count: 1 }],
    ["pool answers another pool", body(BINANCE, ["STXUSDT"])],
    ["the body is a list", ["STXUSDT"]],
    ["the body is null", null],
  ])("rejects a body whose pairs is not an array of strings (%s)", async (_case, malformed) => {
    stubFetch(jsonResponse(malformed));

    const error = await fetchAvailablePairs(BYBIT).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain("available-pairs");
  });

  it("surfaces a structured refusal as an ApiError with its code", async () => {
    stubFetch(
      jsonResponse({ detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "the exchange did not answer" } }, 502),
    );

    const error = (await fetchAvailablePairs(BYBIT).catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.code).toBe("PAIR_CATALOGUE_UNAVAILABLE");
  });
});

describe("useAvailablePairs", () => {
  it("does not fetch until a pool is chosen", async () => {
    const fetchMock = stubFetch(jsonResponse(body(BYBIT, ["STXUSDT"])));
    const { wrapper } = clientWrapper();

    const { result, rerender } = renderHook(({ pool }: { pool: PoolKey | null }) => useAvailablePairs(pool), {
      wrapper,
      initialProps: { pool: null as PoolKey | null },
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.status).toBe("pending");
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ pool: BYBIT });
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.data?.pairs).toEqual(["STXUSDT"]);
  });

  it("uses a query key that is not under ['pools']", async () => {
    stubFetch(jsonResponse(body(BYBIT, ["STXUSDT"])));
    const { client, wrapper } = clientWrapper();

    const { result } = renderHook(() => useAvailablePairs(BYBIT), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("success"));

    const keys = client.getQueryCache().getAll().map((query) => query.queryKey);
    expect(keys).toEqual([["available-pairs", "bybit", "usdt-m", "USDT"]]);
  });

  it("keeps one entry per pool, so one pool's list never answers for another", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(jsonResponse(url.includes("/bybit/") ? body(BYBIT, ["STXUSDT"]) : body(BINANCE, ["SFPUSDT"]))),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { client, wrapper } = clientWrapper();

    const { result, rerender } = renderHook(({ pool }: { pool: PoolKey }) => useAvailablePairs(pool), {
      wrapper,
      initialProps: { pool: BYBIT },
    });
    await waitFor(() => expect(result.current.data?.pairs).toEqual(["STXUSDT"]));
    rerender({ pool: BINANCE });
    await waitFor(() => expect(result.current.data?.pairs).toEqual(["SFPUSDT"]));

    expect(client.getQueryCache().getAll().map((query) => query.queryKey)).toEqual([
      ["available-pairs", "bybit", "usdt-m", "USDT"],
      ["available-pairs", "binance", "usdt-m", "USDT"],
    ]);
  });

  it("is fresh for five minutes and retries a failed read once", async () => {
    stubFetch(jsonResponse(body(BYBIT, ["STXUSDT"])));
    const { client, wrapper } = clientWrapper();

    const { result } = renderHook(() => useAvailablePairs(BYBIT), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("success"));

    const options = client.getQueryCache().getAll()[0]?.observers[0]?.options;
    expect(options?.staleTime).toBe(5 * 60 * 1000);
    expect(options?.retry).toBe(1);
  });

  it("reports a failed read as an error with the refusal's code, never as an empty list", async () => {
    stubFetch(jsonResponse({ detail: { error: "PAIR_CATALOGUE_NOT_SERVED", message: "no catalogue" } }, 404));
    const { wrapper } = clientWrapper();

    const { result } = renderHook(() => useAvailablePairs(BYBIT), { wrapper });
    // The hook retries once (retry: 1), and the first retry waits one second.
    await waitFor(() => expect(result.current.status).toBe("error"), { timeout: 4000 });

    expect(result.current.data).toBeUndefined();
    expect((result.current.error as ApiError).code).toBe("PAIR_CATALOGUE_NOT_SERVED");
  });
});
