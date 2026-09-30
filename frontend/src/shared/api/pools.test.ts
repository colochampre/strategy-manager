import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchPools } from "@/shared/api/pools";
import { lock, pool, unlock } from "@/test/harness";

function respond(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response)),
  );
}

const BALANCE = { total: "120.50", available: "100.25", observed_at: "2026-09-30T10:00:00+00:00", stale: false };

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchPools balance", () => {
  it("keeps the balance, the reserved and the allocatable of each pool as sent", async () => {
    respond([pool("bybit", "linear", "USDT", BALANCE)]);

    const [row] = await fetchPools();

    expect(row?.balance).toEqual(BALANCE);
    expect(row?.reserved).toBe("0");
    expect(row?.allocatable).toBe("100.25");
  });

  it("accepts a pool nothing has synced (balance null)", async () => {
    respond([pool("bybit", "linear")]);

    const [row] = await fetchPools();

    expect(row?.balance).toBeNull();
  });

  it.each([
    ["a balance that is not an object", "100"],
    ["a balance without available", { ...BALANCE, available: undefined }],
    ["a balance with a numeric available", { ...BALANCE, available: 100 }],
    ["a balance without the stale flag", { ...BALANCE, stale: undefined }],
    ["a balance with a non-string observed_at", { ...BALANCE, observed_at: 5 }],
  ])("rejects %s instead of reading it as an unsynced pool", async (_label, balance) => {
    respond([{ ...pool("bybit", "linear"), balance }]);

    await expect(fetchPools()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a row without the balance key at all", async () => {
    const { balance: _balance, ...row } = pool("bybit", "linear");
    respond([row]);

    await expect(fetchPools()).rejects.toBeInstanceOf(ApiError);
  });
});
