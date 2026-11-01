import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import {
  fetchHeldSubscriptions,
  leaveSubscription,
  subscribe,
  useLeaveSubscription,
  useSetSubscriptionShare,
  useSubscribe,
} from "@/shared/api/subscriptions";
import { heldSubscription, jsonResponse, subscriptionOf } from "@/test/harness";

const STRATEGY_ID = "11111111-1111-4111-8111-111111111111";
const SUBSCRIPTION_ID = "33333333-3333-4333-8333-333333333333";

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

/** Each read that names who holds a strategy, marked as fresh, so an invalidation shows on it. */
function holdEveryRead(client: QueryClient) {
  const keys = [
    ["subscriptions", "held"],
    ["strategies", { includeArchived: false }],
    ["strategy", STRATEGY_ID],
    ["public-strategies"],
    ["public-strategies", STRATEGY_ID],
  ];
  for (const key of keys) client.setQueryData(key, []);
  return keys;
}

function stale(client: QueryClient, keys: readonly (readonly unknown[])[]) {
  return keys.filter((key) => client.getQueryState(key)?.isInvalidated === true).length;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHeldSubscriptions", () => {
  it("reads the held route", async () => {
    const row = heldSubscription();
    const fetchMock = stubFetch(jsonResponse([row]));

    await expect(fetchHeldSubscriptions()).resolves.toEqual([row]);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${API_BASE_URL}/api/subscriptions/held`);
  });

  it("takes an author with no name yet", async () => {
    const row = heldSubscription({ author_name: null });
    stubFetch(jsonResponse([row]));

    await expect(fetchHeldSubscriptions()).resolves.toEqual([row]);
  });

  it.each([
    ["a body that is not a list", { rows: [] }],
    ["a row with no strategy name", [heldSubscription({ strategy_name: null })]],
    ["a row with no market", [heldSubscription({ exchange: undefined })]],
    ["a row with an odd authored", [heldSubscription({ authored: "no" })]],
    ["a row that is no subscription", [heldSubscription({ status: "PAUSED" })]],
  ])("refuses %s", async (_name, body) => {
    stubFetch(jsonResponse(body));

    await expect(fetchHeldSubscriptions()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("subscribe", () => {
  it("posts the strategy and the share as the string it is", async () => {
    const fetchMock = stubFetch(jsonResponse(subscriptionOf(STRATEGY_ID, "25.5"), 201));

    await subscribe(STRATEGY_ID, "25.5");

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/subscriptions`);
    expect(call[1].method).toBe("POST");
    expect(new Headers(call[1].headers).get("Content-Type")).toBe("application/json");
    expect(call[1].body).toBe(`{"strategy_id":"${STRATEGY_ID}","allocation_percent":"25.5"}`);
  });

  it("resolves the subscription the server answered", async () => {
    const answer = subscriptionOf(STRATEGY_ID, "25.5");
    stubFetch(jsonResponse(answer, 201));

    await expect(subscribe(STRATEGY_ID, "25.5")).resolves.toEqual(answer);
  });

  it("refuses an answer that is not a subscription", async () => {
    stubFetch(jsonResponse({ id: SUBSCRIPTION_ID }, 201));

    await expect(subscribe(STRATEGY_ID, "25.5")).rejects.toBeInstanceOf(ApiError);
  });

  it("carries the refusal's code", async () => {
    stubFetch(jsonResponse({ detail: { error: "NO_POOL_FOR_MARKET", message: "no pool" } }, 409));

    await expect(subscribe(STRATEGY_ID, "25.5")).rejects.toMatchObject({ status: 409, code: "NO_POOL_FOR_MARKET" });
  });
});

describe("leaveSubscription", () => {
  it("posts to the subscription's leave route with no body", async () => {
    const fetchMock = stubFetch(jsonResponse(subscriptionOf(STRATEGY_ID, "25", { status: "LEAVING" })));

    await leaveSubscription(SUBSCRIPTION_ID);

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/subscriptions/${SUBSCRIPTION_ID}/leave`);
    expect(call[1].method).toBe("POST");
    expect(call[1].body).toBeUndefined();
  });

  it("refuses an answer that is not a subscription", async () => {
    stubFetch(jsonResponse({ id: SUBSCRIPTION_ID }));

    await expect(leaveSubscription(SUBSCRIPTION_ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("what a change makes stale", () => {
  it("a subscribe invalidates every read that names who holds the strategy", async () => {
    stubFetch(jsonResponse(subscriptionOf(STRATEGY_ID, "25"), 201));
    const { client, wrapper } = clientWrapper();
    const keys = holdEveryRead(client);
    const { result } = renderHook(() => useSubscribe(STRATEGY_ID), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("25");
    });

    await waitFor(() => expect(stale(client, keys)).toBe(keys.length));
  });

  it("a refused subscribe does too: the page was wrong about something", async () => {
    stubFetch(jsonResponse({ detail: { error: "ALREADY_SUBSCRIBED", message: "already" } }, 409));
    const { client, wrapper } = clientWrapper();
    const keys = holdEveryRead(client);
    const { result } = renderHook(() => useSubscribe(STRATEGY_ID), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("25").catch(() => undefined);
    });

    await waitFor(() => expect(stale(client, keys)).toBe(keys.length));
  });

  it("a leave invalidates every read that names who holds the strategy", async () => {
    stubFetch(jsonResponse(subscriptionOf(STRATEGY_ID, "25", { status: "ENDED" })));
    const { client, wrapper } = clientWrapper();
    const keys = holdEveryRead(client);
    const { result } = renderHook(() => useLeaveSubscription(STRATEGY_ID, SUBSCRIPTION_ID), { wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    await waitFor(() => expect(stale(client, keys)).toBe(keys.length));
  });

  it("a saved share reaches My subscriptions too", async () => {
    stubFetch(jsonResponse(subscriptionOf(STRATEGY_ID, "25")));
    const { client, wrapper } = clientWrapper();
    holdEveryRead(client);
    const { result } = renderHook(() => useSetSubscriptionShare(STRATEGY_ID, SUBSCRIPTION_ID), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("25");
    });

    await waitFor(() => expect(client.getQueryState(["subscriptions", "held"])?.isInvalidated).toBe(true));
  });
});
