import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchSharePreview, useSharePreview } from "@/shared/api/share-preview";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

/** The hundred whole steps of a pool holding 1000 USDT, each a tenth of its number. */
function steps(): Array<Record<string, unknown>> {
  return Array.from({ length: 100 }, (_, index) => ({
    share: index + 1,
    amount: `${(index + 1) * 10}.000000000000000000`,
    below_pool_minimum: false,
  }));
}

function preview(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    strategy_id: ID,
    pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" },
    currency: "USDT",
    pool_minimum: "5.000000000000000000",
    balance: { total: "1000.000000000000000000", observed_at: "2026-10-08T10:00:00Z", stale: false },
    exact: { share: "33.5", amount: "335.000000000000000000", below_pool_minimum: false },
    steps: steps(),
    ...overrides,
  };
}

/** What a pool nothing has synced answers: no amount, never a zero. */
function unsynced(): Record<string, unknown> {
  return preview({ balance: null, exact: null, steps: [] });
}

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
}

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useTokenStore.setState({ token: null });
});

describe("fetchSharePreview", () => {
  it("requests GET /strategies/{id}/share-preview with no query for the stored share", async () => {
    const fetchMock = stubFetch(preview());

    const body = await fetchSharePreview(ID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/share-preview`);
    expect(call[1].method).toBeUndefined();
    expect(body.exact?.share).toBe("33.5");
    expect(body.steps).toHaveLength(100);
  });

  it("asks with ?share= for an asked one", async () => {
    const fetchMock = stubFetch(preview());

    await fetchSharePreview(ID, "12.25");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[0]).toBe(
      `${API_BASE_URL}/api/strategies/${ID}/share-preview?share=12.25`,
    );
  });

  it("percent-encodes the asked share, so no other parameter can ride on it", async () => {
    const fetchMock = stubFetch(preview());

    await fetchSharePreview(ID, "1&x=2");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[0]).toBe(
      `${API_BASE_URL}/api/strategies/${ID}/share-preview?share=1%26x%3D2`,
    );
  });

  it("accepts the null, null and empty body of a pool nothing has synced", async () => {
    stubFetch(unsynced());

    const body = await fetchSharePreview(ID);

    expect(body.balance).toBeNull();
    expect(body.exact).toBeNull();
    expect(body.steps).toEqual([]);
    expect(body.pool_minimum).toBe("5.000000000000000000");
  });

  it.each([
    ["a balance and no steps", preview({ steps: [] })],
    ["a balance and no exact value", preview({ exact: null })],
    ["exact without a balance", preview({ balance: null, steps: [] })],
    ["steps without a balance", preview({ balance: null, exact: null })],
    ["99 steps", preview({ steps: steps().slice(0, 99) })],
    ["101 steps", preview({ steps: [...steps(), { share: 101, amount: "1010", below_pool_minimum: false }] })],
    ["steps numbered from 0", preview({ steps: steps().map((step) => ({ ...step, share: (step.share as number) - 1 })) })],
    ["steps out of order", preview({ steps: steps().reverse() })],
    ["a step whose share is a string", preview({ steps: steps().map((step) => ({ ...step, share: String(step.share) })) })],
    ["a step whose amount is a JSON number", preview({ steps: steps().map((step) => ({ ...step, amount: 1.5 })) })],
    ["an exact amount that is a JSON number", preview({ exact: { share: "33.5", amount: 335, below_pool_minimum: false } })],
    ["an exact share that is a JSON number", preview({ exact: { share: 33.5, amount: "335", below_pool_minimum: false } })],
    ["a balance total that is a JSON number", preview({ balance: { total: 1000, observed_at: "2026-10-08T10:00:00Z", stale: false } })],
    ["a stale flag that is a string", preview({ balance: { total: "1000", observed_at: "2026-10-08T10:00:00Z", stale: "no" } })],
    ["a pool_minimum that is null", preview({ pool_minimum: null })],
    ["a pool_minimum that is a JSON number", preview({ pool_minimum: 5 })],
    ["no currency", preview({ currency: undefined })],
    ["no pool", preview({ pool: undefined })],
    ["a below_pool_minimum that is not a boolean", preview({ exact: { share: "33.5", amount: "335", below_pool_minimum: "false" } })],
  ])("refuses a body with %s", async (_name, body) => {
    stubFetch(body);

    await expect(fetchSharePreview(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("throws the refusal of the server as an ApiError with its status", async () => {
    stubFetch({ detail: "no such strategy" }, 404);

    const failure = await fetchSharePreview(ID).then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
  });
});

describe("useSharePreview", () => {
  it("makes no request until the hook is mounted", async () => {
    const fetchMock = stubFetch(preview());
    const { wrapper } = clientWrapper();

    expect(fetchMock).not.toHaveBeenCalled();
    const { result } = renderHook(() => useSharePreview(ID), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.data?.exact?.share).toBe("33.5");
  });

  it("the query key is ['strategy', id, 'share-preview'], so a save that invalidates the strategy refreshes it", async () => {
    stubFetch(preview());
    const { client, wrapper } = clientWrapper();
    const { result } = renderHook(() => useSharePreview(ID), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(["strategy", ID, "share-preview"])).toMatchObject({ strategy_id: ID });
    await client.invalidateQueries({ queryKey: ["strategy", ID] });
    expect(client.getQueryState(["strategy", ID, "share-preview"])?.dataUpdateCount).toBe(2);
  });

  it("for an asked share the key is ['strategy', id, 'share-preview', share]", async () => {
    const fetchMock = stubFetch(preview());
    const { client, wrapper } = clientWrapper();
    const { result } = renderHook(() => useSharePreview(ID, "12.25"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(["strategy", ID, "share-preview", "12.25"])).toMatchObject({ strategy_id: ID });
    expect(client.getQueryData(["strategy", ID, "share-preview"])).toBeUndefined();
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[0]).toContain("?share=12.25");
  });

  it("reads again every 60 seconds", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    const fetchMock = stubFetch(preview());
    const { wrapper } = clientWrapper();
    renderHook(() => useSharePreview(ID), { wrapper });

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reads a body it cannot describe as an error, never as a partial table", async () => {
    stubFetch(preview({ steps: steps().slice(0, 99) }));
    const { wrapper } = clientWrapper();
    const { result } = renderHook(() => useSharePreview(ID), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.data).toBeUndefined();
  });
});
