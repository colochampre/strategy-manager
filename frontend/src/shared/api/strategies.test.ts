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
    created_at: "2026-09-01T10:00:00Z",
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the creation date of a strategy", () => {
  it("carries the date, and a null one", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy(), strategy({ created_at: null })])));

    await expect(fetchStrategies(false)).resolves.toMatchObject([
      { created_at: "2026-09-01T10:00:00Z" },
      { created_at: null },
    ]);
  });

  it.each([
    ["a date that is missing", { created_at: undefined }],
    ["a date that is a number", { created_at: 1_790_000_000 }],
  ])("refuses a row with %s", async (_name, overrides) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([strategy(overrides)])));

    await expect(fetchStrategies(false)).rejects.toBeInstanceOf(ApiError);
  });
});
