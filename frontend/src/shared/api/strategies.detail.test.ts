import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import {
  archiveStrategy,
  fetchStrategy,
  fetchStrategyEvents,
  replaceAllowedPairs,
  useArchiveStrategy,
  useReplaceAllowedPairs,
  useStrategy,
} from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
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

describe("fetchStrategy", () => {
  it("reads GET /api/strategies/{id} and returns the strategy", async () => {
    const fetchMock = stubFetch(jsonResponse(strategy({ name: "SOL Trend" })));

    await expect(fetchStrategy(ID)).resolves.toMatchObject({ id: ID, name: "SOL Trend" });

    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}`);
  });

  it("reads a body that is not a strategy as an error, never as a strategy", async () => {
    stubFetch(jsonResponse({ id: ID, name: "no pool" }));
    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("throws a 404 as an ApiError carrying the status", async () => {
    stubFetch(jsonResponse({ detail: "no strategy" }, 404));
    await expect(fetchStrategy(ID)).rejects.toMatchObject({ status: 404 });
  });
});

describe("fetchStrategyEvents", () => {
  it("reads GET /api/strategies/{id}/events", async () => {
    const events = [
      { enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" },
      { enabled: false, occurred_at: "2026-08-20T10:00:00+00:00", origin: "OBSERVED" },
    ];
    const fetchMock = stubFetch(jsonResponse(events));

    await expect(fetchStrategyEvents(ID)).resolves.toEqual(events);

    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/events`);
  });

  it("reads a list with a malformed row as an error, never as a shorter history", async () => {
    stubFetch(jsonResponse([{ enabled: "yes", occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }]));
    await expect(fetchStrategyEvents(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("archiveStrategy", () => {
  it("sends POST /api/strategies/{id}/archive", async () => {
    const fetchMock = stubFetch(jsonResponse(strategy({ archived_at: "2026-10-03T00:00:00+00:00" })));

    await expect(archiveStrategy(ID)).resolves.toMatchObject({ archived_at: "2026-10-03T00:00:00+00:00" });

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/archive`);
    expect(call[1].method).toBe("POST");
  });

  it("keeps the code and the reasons of a 409", async () => {
    const detail = { error: "OPEN_POSITION", message: "open", symbols: ["ETHUSDT"], allocations: [], live_reservations: [], in_flight_attempts: [] };
    stubFetch(jsonResponse({ detail }, 409));

    await expect(archiveStrategy(ID)).rejects.toMatchObject({ status: 409, code: "OPEN_POSITION", fields: detail });
  });
});

describe("replaceAllowedPairs", () => {
  it("sends PUT /api/strategies/{id}/allowed-pairs with the full set", async () => {
    const fetchMock = stubFetch(jsonResponse(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] })));

    await replaceAllowedPairs(ID, ["ETHUSDT", "SOLUSDT"]);

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/allowed-pairs`);
    expect(call[1].method).toBe("PUT");
    expect(JSON.parse(String(call[1].body))).toEqual({ pairs: ["ETHUSDT", "SOLUSDT"] });
  });
});

describe("useStrategy", () => {
  it("does not retry a 404, so a missing strategy is reported at once", async () => {
    const fetchMock = stubFetch(jsonResponse({ detail: "no strategy" }, 404));
    const { wrapper } = clientWrapper();
    const { result } = renderHook(() => useStrategy(ID), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.error).toMatchObject({ status: 404 });
  });
});

describe("the detail mutations", () => {
  it("useArchiveStrategy invalidates the lists and this strategy's queries on success", async () => {
    stubFetch(jsonResponse(strategy({ archived_at: "2026-10-03T00:00:00+00:00" })));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useArchiveStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toContainEqual(["strategies"]);
    expect(keys).toContainEqual(["strategy", ID]);
  });

  it("useArchiveStrategy also invalidates after a refusal, because the stored state is not what the page showed", async () => {
    stubFetch(jsonResponse({ detail: { error: "STILL_ENABLED", message: "enabled" } }, 409));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useArchiveStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));

    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toContainEqual(["strategy", ID]);
  });

  it("useReplaceAllowedPairs invalidates the lists and this strategy's queries, refused or not", async () => {
    for (const response of [jsonResponse(strategy()), jsonResponse({ detail: { error: "PAIRS_CHANGED", message: "changed" } }, 409)]) {
      stubFetch(response);
      const { client, wrapper } = clientWrapper();
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const { result } = renderHook(() => useReplaceAllowedPairs(ID), { wrapper });

      result.current.mutate(["ETHUSDT"]);
      await waitFor(() => expect(result.current.isSuccess || result.current.isError).toBe(true));

      const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
      expect(keys).toContainEqual(["strategies"]);
      expect(keys).toContainEqual(["strategy", ID]);
    }
  });
});
