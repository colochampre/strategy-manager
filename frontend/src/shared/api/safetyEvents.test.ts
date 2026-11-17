import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchSafetyEvents, useSafetyEvents } from "@/shared/api/safetyEvents";
import { lock, unlock } from "@/test/harness";

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn(() =>
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

const EVENT = {
  id: "e1",
  kind: "STOP_FIRED",
  strategy_id: "s1",
  strategy_name: "Breakout",
  allocation_id: "a1",
  exchange: "bybit",
  venue: "usdt-m",
  symbol: "SOLUSDT",
  occurred_at: "2026-11-17T10:00:00+00:00",
  detail: { quantity: "0.5", trigger_price: "140" },
};

describe("fetchSafetyEvents", () => {
  it("returns a well-formed body as the route sent it, asking GET /api/safety-events", async () => {
    const fetchMock = respond({ events: [EVENT, { ...EVENT, id: "e2", allocation_id: null }] });
    const answer = await fetchSafetyEvents();
    expect(answer.events.map((event) => event.id)).toEqual(["e1", "e2"]);
    expect(String((fetchMock.mock.calls as unknown[][])[0]?.[0])).toMatch(/\/api\/safety-events$/);
  });

  it("accepts an empty list", async () => {
    respond({ events: [] });
    expect((await fetchSafetyEvents()).events).toEqual([]);
  });

  it("keeps a kind it does not know, with whatever detail it carries", async () => {
    respond({ events: [{ ...EVENT, kind: "SOMETHING_NEW", detail: {} }] });
    expect((await fetchSafetyEvents()).events[0]?.kind).toBe("SOMETHING_NEW");
  });

  it.each([
    ["a body with no events list", {}],
    ["events that is not a list", { events: "none" }],
    ["an event with no id", { events: [{ ...EVENT, id: undefined }] }],
    ["an event whose time cannot be read", { events: [{ ...EVENT, occurred_at: "yesterday" }] }],
    ["an event with no strategy name", { events: [{ ...EVENT, strategy_name: undefined }] }],
    ["an event whose detail is not an object", { events: [{ ...EVENT, detail: "x" }] }],
    ["a detail value that is not text", { events: [{ ...EVENT, detail: { quantity: 0.5 } }] }],
    ["one bad element among good ones", { events: [EVENT, { ...EVENT, symbol: 7 }] }],
  ])("refuses %s as an ApiError, never as an empty list", async (_name, body) => {
    respond(body);
    await expect(fetchSafetyEvents()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("useSafetyEvents", () => {
  function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return createElement(QueryClientProvider, { client }, children);
  }

  it("exposes the answer", async () => {
    respond({ events: [EVENT] });
    const { result } = renderHook(() => useSafetyEvents(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data?.events).toHaveLength(1);
  });

  it("is an error state on a bad shape", async () => {
    respond({ nope: true });
    const { result } = renderHook(() => useSafetyEvents(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
  });
});
