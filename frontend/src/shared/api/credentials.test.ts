import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchCredentials } from "@/shared/api/credentials";
import served from "@/shared/credentials/served-exchanges.json";
import { emptyKey, lock, storedKey, unlock } from "@/test/harness";

function respond(body: unknown) {
  const fetchMock = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchCredentials, the rows that are believed", () => {
  it.each([
    ["a key the venue verified", { ...storedKey("bybit"), trade_capability_source: "VERIFIED", withdraw_check: "VERIFIED" }],
    [
      "a key the owner confirmed",
      {
        ...storedKey("binance"),
        trade_capability_source: "OWNER_CONFIRMED",
        withdraw_check: "OWNER_CONFIRMED",
        trade_confirmed_at: "2026-10-02T09:00:00Z",
        withdraw_confirmed_at: "2026-10-02T09:00:00Z",
        internal_transfer: null,
      },
    ],
    [
      "a key sealed before the facts were kept",
      { ...storedKey("bybit"), trade_capability_source: "UNRECORDED", withdraw_check: "UNRECORDED", validated_at: null },
    ],
    ["a key that cannot trade", { ...storedKey("bybit"), trade_capable: false }],
    ["a key that may move money between the owner's accounts", { ...storedKey("bybit"), internal_transfer: true }],
    ["a key that may not", { ...storedKey("bybit"), internal_transfer: false }],
    ["a key with no recorded transfer fact", { ...storedKey("bybit"), internal_transfer: null }],
    ["a key whose timestamps are all null", { ...storedKey("bybit"), stored_at: null, validated_at: null }],
    ["an exchange with no key", emptyKey("binance")],
  ])("reads %s as sent", async (_label, row) => {
    respond([row]);

    const entries = await fetchCredentials();

    expect(entries).toEqual([row]);
  });

  it("keeps the order of the rows and reads an empty list as no entries", async () => {
    respond([storedKey("bybit"), emptyKey("binance")]);
    const two = await fetchCredentials();

    respond([]);
    const none = await fetchCredentials();

    expect(two.map((entry) => entry.exchange)).toEqual(["bybit", "binance"]);
    expect(none).toEqual([]);
  });

  it("asks for GET /api/credentials once and nothing else", async () => {
    const fetchMock = respond([storedKey("bybit")]);

    await fetchCredentials();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/api/credentials`);
    expect(init.method ?? "GET").toBe("GET");
    expect(init.body).toBeUndefined();
  });
});

describe("fetchCredentials, the rows that make the whole read an error", () => {
  it.each([
    ["an empty exchange", { ...storedKey("bybit"), exchange: "" }],
    ["an exchange that is not a string", { ...storedKey("bybit"), exchange: 7 }],
    ["a status that is neither STORED nor EMPTY", { ...storedKey("bybit"), status: "ACTIVE" }],
    ["no status", { ...storedKey("bybit"), status: undefined }],
    ["a last4 of three characters", { ...storedKey("bybit"), last4: "123" }],
    ["a last4 of five characters", { ...storedKey("bybit"), last4: "12345" }],
    ["a last4 of twelve characters", { ...storedKey("bybit"), last4: "ABCDEFGHIJKL" }],
    ["a stored row with a null last4", { ...storedKey("bybit"), last4: null }],
    ["a last4 that is not a string", { ...storedKey("bybit"), last4: 1234 }],
    ["a trade_capable that is not a boolean", { ...storedKey("bybit"), trade_capable: "true" }],
    ["a trade_capable that is null on a stored row", { ...storedKey("bybit"), trade_capable: null }],
    ["a trade capability source that is not a string", { ...storedKey("bybit"), trade_capability_source: 3 }],
    ["a withdraw check that is not a string", { ...storedKey("bybit"), withdraw_check: false }],
    ["a validated_at that is a number", { ...storedKey("bybit"), validated_at: 1_760_000_000 }],
    ["a stored_at that is a number", { ...storedKey("bybit"), stored_at: 1_760_000_000 }],
    ["a trade_confirmed_at that is a number", { ...storedKey("bybit"), trade_confirmed_at: 1_760_000_000 }],
    ["a withdraw_confirmed_at that is a number", { ...storedKey("bybit"), withdraw_confirmed_at: 1_760_000_000 }],
    ["an internal_transfer that is a string", { ...storedKey("bybit"), internal_transfer: "no" }],
    ["a row that is not an object", "bybit"],
    ["a null row", null],
  ])("rejects %s", async (_label, row) => {
    respond([row]);

    await expect(fetchCredentials()).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["an object", { exchanges: [] }],
    ["null", null],
    ["a string", "[]"],
    ["a number", 3],
  ])("rejects a body that is %s, never reading it as no keys", async (_label, body) => {
    respond(body);

    await expect(fetchCredentials()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects the whole list when one row among good ones is bad", async () => {
    respond([storedKey("bybit"), { ...storedKey("binance"), last4: "12" }, emptyKey("pionex")]);

    await expect(fetchCredentials()).rejects.toBeInstanceOf(ApiError);
  });

  // The page's half is task 13.4.7: the page shows the error and no card.
  it("test_a_last4_that_is_not_four_characters_is_refused_and_never_rendered", async () => {
    const wholeKey = "FAKE-WHOLE-KEY-0000";
    respond([{ ...storedKey("bybit"), last4: wholeKey }]);

    const error = (await fetchCredentials().catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).not.toContain(wholeKey);
    expect(JSON.stringify(Object.getOwnPropertyNames(error).map((name) => String(Reflect.get(error, name))))).not.toContain(
      wholeKey,
    );
  });
});

describe("served-exchanges.json", () => {
  it("lists bybit then binance, in display order", () => {
    expect(Object.keys(served)).toEqual(["bybit", "binance"]);
  });

  it("asks nothing of Bybit and both confirmations of Binance, in the form's order", () => {
    expect(served.bybit.confirmations).toEqual([]);
    expect(served.binance.confirmations).toEqual(["withdrawals_disabled_confirmed", "futures_enabled_confirmed"]);
  });
});
