import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategies, fetchStrategy, useRegenerateWebhookSecret } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { jsonResponse, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Record<string, unknown> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscriptionOf(ID, "100"),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    secret_last4: "x4F2",
    ...overrides,
  } as Strategy;
}

function withoutLast4(): Record<string, unknown> {
  const { secret_last4: _omitted, ...rest } = strategy();
  return rest;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a strategy carries the last four of its webhook secret", () => {
  it("keeps secret_last4 from the list and from the detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy({ secret_last4: "Qm7_" })])));
    const listed = await fetchStrategies(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(strategy({ secret_last4: "Qm7_" }))));
    const one = await fetchStrategy(ID);

    expect(listed[0]?.secret_last4).toBe("Qm7_");
    expect(one.secret_last4).toBe("Qm7_");
  });

  it.each([
    ["absent", withoutLast4()],
    ["three characters", strategy({ secret_last4: "x4F" })],
    ["five characters", strategy({ secret_last4: "x4F2z" })],
    ["a number", strategy({ secret_last4: 1234 })],
    ["null", strategy({ secret_last4: null })],
  ])("reads a strategy whose secret_last4 is %s as an error, never as a strategy", async (_label, row) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([row])));
    await expect(fetchStrategies(false)).rejects.toBeInstanceOf(ApiError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(row)));
    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("useRegenerateWebhookSecret", () => {
  function clientWrapper() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    return { client, wrapper };
  }

  it("reads the strategy again once a new secret is issued, so the mask follows the secret", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ webhook_secret: "a-new-secret-0000" })));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRegenerateWebhookSecret(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([["strategies"], ["strategy", ID]]);
  });

  it("reads nothing again when the secret was not regenerated", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRegenerateWebhookSecret(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidate).not.toHaveBeenCalled();
  });
});
