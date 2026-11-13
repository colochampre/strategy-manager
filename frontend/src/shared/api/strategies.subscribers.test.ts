import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategies } from "@/shared/api/strategies";
import { jsonResponse } from "@/test/harness";

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 60, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 3,
    live_subscribers: 2,
    created_at: null,
    capital: "300",
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the author's total on a strategy", () => {
  it("carries both counts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy()])));

    await expect(fetchStrategies(false)).resolves.toMatchObject([{ subscribers: 3, live_subscribers: 2 }]);
  });

  it.each([
    ["a total that is missing", { subscribers: undefined }],
    ["a live count that is missing", { live_subscribers: undefined }],
    ["a total that is a string", { subscribers: "3" }],
    ["a live count that is fractional", { live_subscribers: 1.5 }],
    ["a total that is negative", { subscribers: -1 }],
    ["a capital that is missing", { capital: undefined }],
    ["a capital that is a number", { capital: 300 }],
  ])("refuses %s", async (_name, overrides) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy(overrides)])));

    await expect(fetchStrategies(false)).rejects.toBeInstanceOf(ApiError);
  });

  it("carries the capital, and a null one under the brake", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse([strategy(), strategy({ capital: null })])),
    );

    await expect(fetchStrategies(false)).resolves.toMatchObject([{ capital: "300" }, { capital: null }]);
  });
});
