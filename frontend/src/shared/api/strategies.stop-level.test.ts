import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategy, registerStrategy, setStrategyStopLevel } from "@/shared/api/strategies";
import { jsonResponse, subscriptionOf } from "@/test/harness";

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
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a strategy carries its stop level", () => {
  it("keeps the level as the string the server wrote, never as a number", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(strategy({ stop_loss_pct: "7.50" }))));

    expect((await fetchStrategy(ID)).stop_loss_pct).toBe("7.50");
  });

  it("reads a strategy with no level as an error, never as one with no cap", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(strategy({ stop_loss_pct: undefined }))));

    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("reads a level that is a number as an error, never as a strategy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(strategy({ stop_loss_pct: 10 }))));

    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("saving the stop level", () => {
  it("PATCHes only stop_loss_pct, as the string typed, and answers the checked strategy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(strategy({ stop_loss_pct: "7.50" })));
    vi.stubGlobal("fetch", fetchMock);

    const saved = await setStrategyStopLevel(ID, "7.5");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/strategies/${ID}`);
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(JSON.stringify({ stop_loss_pct: "7.5" }));
    expect(saved.stop_loss_pct).toBe("7.50");
  });

  it("registering carries the level beside the leverage", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...strategy(), webhook_secret: "s3cret" }, 201));
    vi.stubGlobal("fetch", fetchMock);

    await registerStrategy({
      id: ID,
      name: "ETH Breakout",
      exchange: "bybit",
      venue: "usdt-m",
      settlement_currency: "USDT",
      fill_mode: "SKIP",
      allocation_percent: "100",
      leverage: 9,
      stop_loss_pct: "10",
      visibility: "PRIVATE",
      allowed_pairs: ["ETHUSDT"],
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({ leverage: 9, stop_loss_pct: "10" });
  });
});
