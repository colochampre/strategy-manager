import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/shared/api/client";
import { fetchCredentials } from "@/shared/api/credentials";
import type { CredentialEntry } from "@/shared/api/credentials";
import { emptyKey, pool, storedKey, stubApi } from "@/test/harness";

const HEALTH = { kind: "ok", body: {} } as const;

/** The read, asserted to have succeeded, so a stub that does not answer fails on an assertion. */
async function readCredentials(): Promise<CredentialEntry[]> {
  const [settled] = await Promise.allSettled([fetchCredentials()]);
  expect(settled?.status).toBe("fulfilled");
  return settled?.status === "fulfilled" ? settled.value : [];
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("stubApi's default answer for GET /credentials", () => {
  it("answers one STORED, VERIFIED, trade-capable entry per distinct exchange of a pools list", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit"), pool("binance")] });

    const entries = await readCredentials();

    expect(entries).toEqual([storedKey("bybit"), storedKey("binance")]);
    for (const entry of entries) {
      expect(entry).toMatchObject({
        status: "STORED",
        trade_capable: true,
        trade_capability_source: "VERIFIED",
        withdraw_check: "VERIFIED",
      });
    }
  });

  it("answers one entry for two pools of one exchange", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "usdt-m"), pool("bybit", "spot"), pool("binance")] });

    const entries = await readCredentials();

    expect(entries.map((entry) => entry.exchange)).toEqual(["bybit", "binance"]);
  });

  it("answers the one Bybit key of the harness's default pools when a test names no pools", async () => {
    stubApi(HEALTH);

    const entries = await readCredentials();

    expect(entries.map((entry) => entry.exchange)).toEqual(["bybit"]);
  });

  it.each([
    ["a pools read that fails", { kind: "status", status: 500, body: {} }],
    ["a pools read that cannot reach the network", { kind: "network-error" }],
    ["a pools body that is not a list", { kind: "ok", body: { not: "a list" } }],
  ] as const)("answers an empty list with %s", async (_label, pools) => {
    stubApi(HEALTH, [], pools);

    const entries = await readCredentials();

    expect(entries).toEqual([]);
  });

  it("lets an explicit seventh argument win over the default", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] }, {}, undefined, {}, {
      kind: "ok",
      body: [emptyKey("bybit"), storedKey("binance", { trade_capable: false })],
    });

    const entries = await readCredentials();

    expect(entries).toEqual([emptyKey("bybit"), storedKey("binance", { trade_capable: false })]);
  });

  it("lets an explicit seventh argument fail the read", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] }, {}, undefined, {}, { kind: "status", status: 503 });

    await expect(fetchCredentials()).rejects.toMatchObject({ status: 503 });
  });
});

describe("stubApi never answers a write to /credentials by default", () => {
  it("rejects a PUT and a DELETE and records their URLs in fetchMock.unexpected", async () => {
    const fetchMock = stubApi(HEALTH);

    await expect(apiFetch("/credentials/bybit", { method: "PUT", body: "{}" })).rejects.toMatchObject({ status: 0 });
    await expect(apiFetch("/credentials/binance", { method: "DELETE" })).rejects.toMatchObject({ status: 0 });

    expect(fetchMock.unexpected).toHaveLength(2);
    expect(fetchMock.unexpected[0]).toMatch(/\/credentials\/bybit$/);
    expect(fetchMock.unexpected[1]).toMatch(/\/credentials\/binance$/);
  });

  it("leaves fetchMock.unexpected empty for requests it answered", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] });

    await readCredentials();
    await apiFetch("/pools");
    await apiFetch("/health");

    expect(fetchMock.mock.calls).toHaveLength(3);
    expect(fetchMock.unexpected).toEqual([]);
  });

  it("records an unknown URL too", async () => {
    const fetchMock = stubApi(HEALTH);

    await expect(apiFetch("/nothing-serves-this")).rejects.toMatchObject({ status: 0 });

    expect(fetchMock.unexpected).toHaveLength(1);
    expect(fetchMock.unexpected[0]).toMatch(/\/nothing-serves-this$/);
  });
});

describe("the key builders", () => {
  it.each([
    ["no override", {}],
    ["a key that cannot trade", { trade_capable: false }],
    ["another last4", { last4: "ab12" }],
    ["an owner-confirmed key", { trade_capability_source: "OWNER_CONFIRMED", withdraw_check: "OWNER_CONFIRMED" }],
    ["an unrecorded key", { trade_capability_source: "UNRECORDED", withdraw_check: "UNRECORDED", validated_at: null }],
    ["a transfer fact that is null", { internal_transfer: null }],
  ])("storedKey with %s passes fetchCredentials's check and applies the override", async (_label, overrides) => {
    const row = storedKey("bybit", overrides);
    stubApi(HEALTH, [], { kind: "ok", body: [] }, {}, undefined, {}, { kind: "ok", body: [row] });

    const entries = await readCredentials();

    expect(entries).toEqual([row]);
    expect(row).toMatchObject({ exchange: "bybit", status: "STORED", ...overrides });
  });

  it("storedKey keeps the exchange it is given", () => {
    expect(storedKey("binance").exchange).toBe("binance");
    expect(storedKey("bybit").exchange).toBe("bybit");
  });

  it.each(["bybit", "binance", "pionex"])("emptyKey(%s) passes fetchCredentials's check as an EMPTY row", async (exchange) => {
    const row = emptyKey(exchange);
    stubApi(HEALTH, [], { kind: "ok", body: [] }, {}, undefined, {}, { kind: "ok", body: [row] });

    const entries = await readCredentials();

    expect(entries).toEqual([row]);
    expect(row).toMatchObject({ exchange, status: "EMPTY" });
  });
});
