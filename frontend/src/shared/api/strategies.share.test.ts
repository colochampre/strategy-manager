import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { setStrategyAllocationPercent, useSetAllocationPercent } from "@/shared/api/strategies";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: ID,
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "33.5",
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 60, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    ...overrides,
  };
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
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
  useTokenStore.setState({ token: null });
});

describe("setStrategyAllocationPercent", () => {
  it('sends PATCH /api/strategies/{id} with exactly {"allocation_percent":"33.5"}', async () => {
    const fetchMock = stubFetch(jsonResponse(strategy()));

    await setStrategyAllocationPercent(ID, "33.5");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}`);
    expect(call[1].method).toBe("PATCH");
    expect(new Headers(call[1].headers).get("Content-Type")).toBe("application/json");
    expect(call[1].body).toBe('{"allocation_percent":"33.5"}');
  });

  it.each(["33.5", "0.5", "100"])("sends the value %s as a string and no other field", async (value) => {
    const fetchMock = stubFetch(jsonResponse(strategy({ allocation_percent: value })));

    await setStrategyAllocationPercent(ID, value);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["allocation_percent"]);
    expect(body.allocation_percent).toBe(value);
  });

  it("resolves the strategy the server answered", async () => {
    stubFetch(jsonResponse(strategy({ allocation_percent: "12.25" })));

    const answered = await setStrategyAllocationPercent(ID, "12.25");

    expect(answered.allocation_percent).toBe("12.25");
    expect(answered.id).toBe(ID);
  });

  it("refuses an answer that is not a strategy", async () => {
    stubFetch(jsonResponse({ id: ID, allocation_percent: "33.5" }));

    await expect(setStrategyAllocationPercent(ID, "33.5")).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    [422, "The share must be above 0 and at most 100."],
    [409, "archived"],
    [404, "no strategy"],
    [500, "boom"],
  ])("a refusal (%i) throws an ApiError with its status", async (status, detail) => {
    stubFetch(jsonResponse({ detail }, status));

    const failure = await setStrategyAllocationPercent(ID, "33.5").then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(status);
    expect((failure as ApiError).detail).toBe(detail);
  });
});

describe("useSetAllocationPercent", () => {
  it("on success writes the checked answer into ['strategy', id], and only that strategy's", async () => {
    stubFetch(jsonResponse(strategy({ allocation_percent: "40" })));
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], strategy());
    client.setQueryData(["strategy", OTHER_ID], strategy({ id: OTHER_ID }));
    const { result } = renderHook(() => useSetAllocationPercent(ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(["strategy", ID])).toEqual(strategy({ allocation_percent: "40" }));
    expect(client.getQueryData(["strategy", OTHER_ID])).toEqual(strategy({ id: OTHER_ID }));
  });

  it("writes nothing when the save is refused", async () => {
    stubFetch(jsonResponse({ detail: "no" }, 422));
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], strategy());
    const { result } = renderHook(() => useSetAllocationPercent(ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(["strategy", ID])).toEqual(strategy());
  });

  it("on settle invalidates ['strategies'] and ['strategy', id] and returns that promise", async () => {
    stubFetch(jsonResponse(strategy({ allocation_percent: "40" })));
    const { client, wrapper } = clientWrapper();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockImplementation(() => gate);
    const { result } = renderHook(() => useSetAllocationPercent(ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(invalidate).toHaveBeenCalled());

    // The invalidation has not finished, so the mutation has not settled: the hook returned its promise.
    expect(result.current.isSuccess).toBe(false);
    release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([["strategies"], ["strategy", ID]]);
  });

  it("on a refusal still invalidates both keys, so the page reads the stored state again", async () => {
    stubFetch(jsonResponse({ detail: "archived" }, 409));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSetAllocationPercent(ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([["strategies"], ["strategy", ID]]);
  });
});
