import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategies, fetchStrategy } from "@/shared/api/strategies";
import { fetchPublicStrategies, fetchPublicStrategy } from "@/shared/api/public-strategies";
import { jsonResponse, publicStrategy, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    capital: null,
    ...overrides,
  };
}

function without(row: Record<string, unknown>): Record<string, unknown> {
  const { description: _omitted, ...rest } = row;
  return rest;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a strategy carries its description", () => {
  it("keeps a text and a null from the list and from the detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy({ description: "Runs at 3x" }), strategy()])));
    const listed = await fetchStrategies(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(strategy({ description: "Runs at 3x" }))));
    const one = await fetchStrategy(ID);

    expect(listed.map((row) => row.description)).toEqual(["Runs at 3x", null]);
    expect(one.description).toBe("Runs at 3x");
  });

  it.each([
    ["absent", without(strategy())],
    ["a number", strategy({ description: 7 })],
  ])("reads a strategy whose description is %s as an error, never as a strategy", async (_label, row) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([row])));
    await expect(fetchStrategies(false)).rejects.toBeInstanceOf(ApiError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(row)));
    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("a public strategy carries its description", () => {
  it("keeps a text and a null from the list and from the detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse([publicStrategy({ description: "Runs at 3x" }), publicStrategy()])),
    );
    const listed = await fetchPublicStrategies();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(publicStrategy({ description: "Runs at 3x" }))));
    const one = await fetchPublicStrategy(ID);

    expect(listed.map((row) => row.description)).toEqual(["Runs at 3x", null]);
    expect(one.description).toBe("Runs at 3x");
  });

  it.each([
    ["absent", without(publicStrategy())],
    ["a number", publicStrategy({ description: 7 })],
  ])("reads a public strategy whose description is %s as an error", async (_label, row) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([row])));
    await expect(fetchPublicStrategies()).rejects.toBeInstanceOf(ApiError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(row)));
    await expect(fetchPublicStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});
