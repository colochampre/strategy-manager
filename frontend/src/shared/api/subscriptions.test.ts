import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { isSubscription, setSubscriptionShare, useSetSubscriptionShare } from "@/shared/api/subscriptions";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";
const SUBSCRIPTION_ID = "33333333-3333-4333-8333-333333333333";

function subscription(overrides: Record<string, unknown> = {}) {
  return {
    id: SUBSCRIPTION_ID,
    strategy_id: ID,
    pool_id: 7,
    allocation_percent: "33.5",
    status: "ACTIVE",
    created_at: "2026-10-27T10:00:00Z",
    left_at: null,
    ended_at: null,
    ...overrides,
  };
}

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: ID,
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscription(),
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 60, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    visibility: "PRIVATE",
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("isSubscription", () => {
  it.each(["ACTIVE", "LEAVING", "ENDED"])("accepts a subscription that is %s", (status) => {
    expect(isSubscription(subscription({ status, left_at: status === "ACTIVE" ? null : "2026-10-28T10:00:00Z" }))).toBe(true);
  });

  it.each([
    ["an unknown status", { status: "PAUSED" }],
    ["a share that is a number", { allocation_percent: 33.5 }],
    ["a pool id that is a string", { pool_id: "7" }],
    ["no id", { id: undefined }],
    ["a left_at that is not a string", { left_at: 1 }],
  ])("refuses %s", (_case, overrides) => {
    expect(isSubscription(subscription(overrides))).toBe(false);
  });

  it("refuses what is not an object", () => {
    expect(isSubscription(null)).toBe(false);
    expect(isSubscription([subscription()])).toBe(false);
  });
});

describe("setSubscriptionShare", () => {
  it('sends PATCH /api/subscriptions/{id} with exactly {"allocation_percent":"33.5"}', async () => {
    const fetchMock = stubFetch(jsonResponse(subscription()));

    await setSubscriptionShare(SUBSCRIPTION_ID, "33.5");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/subscriptions/${SUBSCRIPTION_ID}`);
    expect(call[1].method).toBe("PATCH");
    expect(new Headers(call[1].headers).get("Content-Type")).toBe("application/json");
    expect(call[1].body).toBe('{"allocation_percent":"33.5"}');
  });

  it("resolves the subscription the server answered", async () => {
    stubFetch(jsonResponse(subscription({ allocation_percent: "12.25" })));

    const answered = await setSubscriptionShare(SUBSCRIPTION_ID, "12.25");

    expect(answered).toEqual(subscription({ allocation_percent: "12.25" }));
  });

  it("refuses an answer that is not a subscription", async () => {
    stubFetch(jsonResponse({ id: SUBSCRIPTION_ID, allocation_percent: "33.5" }));

    await expect(setSubscriptionShare(SUBSCRIPTION_ID, "33.5")).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    [422, "The share must be above 0 and at most 100."],
    [409, { error: "SUBSCRIPTION_NOT_ACTIVE", message: "not active" }],
    [404, "no subscription"],
    [500, "boom"],
  ])("a refusal (%i) throws an ApiError with its status", async (status, detail) => {
    stubFetch(jsonResponse({ detail }, status));

    const failure = await setSubscriptionShare(SUBSCRIPTION_ID, "33.5").then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(status);
  });
});

describe("useSetSubscriptionShare", () => {
  it("on success writes the answer into the strategy's subscription under ['strategy', id], and only there", async () => {
    stubFetch(jsonResponse(subscription({ allocation_percent: "40" })));
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], strategy());
    client.setQueryData(["strategy", OTHER_ID], strategy({ id: OTHER_ID }));
    const { result } = renderHook(() => useSetSubscriptionShare(ID, SUBSCRIPTION_ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(["strategy", ID])).toEqual(strategy({ subscription: subscription({ allocation_percent: "40" }) }));
    expect(client.getQueryData(["strategy", OTHER_ID])).toEqual(strategy({ id: OTHER_ID }));
  });

  it("writes nothing when the save is refused", async () => {
    stubFetch(jsonResponse({ detail: "no" }, 422));
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], strategy());
    const { result } = renderHook(() => useSetSubscriptionShare(ID, SUBSCRIPTION_ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(["strategy", ID])).toEqual(strategy());
  });

  it("on settle invalidates ['strategies'] and ['strategy', id] and returns that promise", async () => {
    stubFetch(jsonResponse(subscription({ allocation_percent: "40" })));
    const { client, wrapper } = clientWrapper();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockImplementation(() => gate);
    const { result } = renderHook(() => useSetSubscriptionShare(ID, SUBSCRIPTION_ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(invalidate).toHaveBeenCalled());

    // The invalidation has not finished, so the mutation has not settled: the hook returned its promise.
    expect(result.current.isSuccess).toBe(false);
    release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([["strategies"], ["strategy", ID]]);
  });

  it("on a refusal still invalidates both keys, so the page reads the stored state again", async () => {
    stubFetch(jsonResponse({ detail: { error: "SUBSCRIPTION_NOT_ACTIVE", message: "not active" } }, 409));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSetSubscriptionShare(ID, SUBSCRIPTION_ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([["strategies"], ["strategy", ID]]);
  });

  it("invalidates no ['positions','open']", async () => {
    stubFetch(jsonResponse(subscription({ allocation_percent: "40" })));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSetSubscriptionShare(ID, SUBSCRIPTION_ID), { wrapper });

    result.current.mutate("40");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).not.toContainEqual(["positions", "open"]);
  });
});
