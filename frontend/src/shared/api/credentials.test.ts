import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode, createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import {
  deleteCredential,
  fetchCredentials,
  saveCredential,
  useCredentials,
  useDeleteCredential,
} from "@/shared/api/credentials";
import type { DeleteResult, SaveResult } from "@/shared/api/credentials";
import { usePools } from "@/shared/api/pools";
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

// Two fixed fake strings. Neither is a credential: the tests need no real one (DRY_RUN, rule 1).
const K = "FAKE-KEY-SENTINEL-AAAA9999";
const S = "FAKE-SECRET-SENTINEL-BBBB8888";

function answer(status: number, body: unknown) {
  const fetchMock = vi.fn(() =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function failToConnect(error: Error = new TypeError("Failed to fetch")) {
  const fetchMock = vi.fn(() => Promise.reject(error));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const SAVED_BODY = {
  last4: "5678",
  facts: { trade_capable: true, validated_at: "2026-10-10T10:00:00Z" },
  warnings: [] as string[],
};

describe("saveCredential, a save that worked", () => {
  it("is saved with the last four characters the server answered", async () => {
    answer(200, SAVED_BODY);

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "saved", last4: "5678", readOnly: false });
  });

  it("reads another last4 the same way", async () => {
    answer(200, { ...SAVED_BODY, last4: "ab12" });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "saved", last4: "ab12", readOnly: false });
  });

  it.each([
    ["three characters", "123"],
    ["five characters", "12345"],
    ["the whole of the key", K],
    ["a number", 5678],
    ["null", null],
  ])("keeps no last4 when the answer's is %s", async (_label, last4) => {
    answer(200, { ...SAVED_BODY, last4 });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "saved", last4: null, readOnly: false });
  });

  it("is read-only when the warnings hold READ_ONLY_KEY", async () => {
    answer(200, { ...SAVED_BODY, warnings: ["READ_ONLY_KEY"] });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "saved", last4: "5678", readOnly: true });
  });

  it("is read-only when the facts say the key cannot trade, with no warning at all", async () => {
    answer(200, { ...SAVED_BODY, facts: { trade_capable: false }, warnings: [] });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "saved", last4: "5678", readOnly: true });
  });

  it.each([
    ["a body that is null", null],
    ["a body that is a string", "saved"],
    ["a body without facts or warnings", { last4: "5678" }],
  ])("is still saved for a 200 with %s", async (_label, body) => {
    answer(200, body);

    const result = await saveCredential("bybit", K, S, []);

    expect(result.kind).toBe("saved");
  });

  // A 200 of this route always carries JSON, so a body that cannot be read came from something
  // else on the way. The panel does not know whether the key was stored and must never say it was.
  it("is unknown, never saved, when the 200's body cannot be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.reject(new SyntaxError("Unexpected end of JSON input")),
        } as unknown as Response),
      ),
    );

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "unknown", missing: [], status: 200 });
  });
});

describe("saveCredential, every refusal by the outcome or the status", () => {
  it.each([
    [422, "KEY_REJECTED", "keyRejected"],
    [422, "WITHDRAW_PERMISSION", "withdrawPermission"],
    [422, "PERMISSIONS_UNAVAILABLE", "permissionsUnavailable"],
    [502, "VENUE_UNREACHABLE", "venueUnreachable"],
    [409, "CONCURRENT_SAVE", "concurrentSave"],
    [422, "CONFIRMATION_NOT_APPLICABLE", "confirmationNotApplicable"],
  ])("a %i %s is %s", async (status, outcome, reason) => {
    answer(status, { outcome, detail: "text the panel never shows" });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason, missing: [], status });
  });

  it("a 422 CONFIRMATION_REQUIRED carries the missing names the response lists at its top level", async () => {
    answer(422, {
      outcome: "CONFIRMATION_REQUIRED",
      detail: "binance cannot be checked by this panel; confirm: futures_enabled_confirmed",
      missing: ["futures_enabled_confirmed"],
    });

    const result = await saveCredential("binance", K, S, ["withdrawals_disabled_confirmed"]);

    expect(result).toEqual({
      kind: "refused",
      reason: "confirmationRequired",
      missing: ["futures_enabled_confirmed"],
      status: 422,
    });
  });

  it("a CONFIRMATION_REQUIRED lists both names when both are missing", async () => {
    answer(422, {
      outcome: "CONFIRMATION_REQUIRED",
      detail: "x",
      missing: ["withdrawals_disabled_confirmed", "futures_enabled_confirmed"],
    });

    const result = await saveCredential("binance", K, S, []);

    expect(result).toEqual({
      kind: "refused",
      reason: "confirmationRequired",
      missing: ["withdrawals_disabled_confirmed", "futures_enabled_confirmed"],
      status: 422,
    });
  });

  it.each([
    ["a string", "futures_enabled_confirmed"],
    ["an object", { name: "futures_enabled_confirmed" }],
    ["null", null],
    ["absent", undefined],
  ])("a CONFIRMATION_REQUIRED whose missing is %s lists none", async (_label, missing) => {
    answer(422, { outcome: "CONFIRMATION_REQUIRED", detail: "x", missing });

    const result = await saveCredential("binance", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "confirmationRequired", missing: [], status: 422 });
  });

  it("a 404 is notServed", async () => {
    answer(404, { detail: "exchange 'pionex' is not served by this panel" });

    const result = await saveCredential("pionex", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "notServed", missing: [], status: 404 });
  });

  it("a 503 is storageUnavailable", async () => {
    answer(503, { detail: "credential storage is not configured" });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "storageUnavailable", missing: [], status: 503 });
  });

  it.each([
    ["the key", [{ type: "string_too_short", loc: ["body", "api_key"], msg: "short" }], "invalidKey"],
    ["the secret", [{ type: "string_pattern_mismatch", loc: ["body", "api_secret"], msg: "bad" }], "invalidSecret"],
    [
      "both, which is read as the key",
      [
        { type: "string_too_short", loc: ["body", "api_secret"], msg: "short" },
        { type: "string_too_short", loc: ["body", "api_key"], msg: "short" },
      ],
      "invalidKey",
    ],
    ["neither", [{ type: "string_too_long", loc: ["body", "label"], msg: "long" }], "invalidRequest"],
    ["nothing at all", [], "invalidRequest"],
    ["an entry with no location", [{ type: "x", msg: "y" }], "invalidRequest"],
  ])("a pydantic 422 naming %s gives its own reason", async (_label, detail, reason) => {
    answer(422, { detail });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason, missing: [], status: 422 });
  });

  it("no answer at all is noAnswer, with status 0", async () => {
    failToConnect();

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "noAnswer", missing: [], status: 0 });
  });

  it.each([
    [500, { detail: "Internal Server Error" }],
    [502, { detail: "Bad Gateway" }],
    [429, { detail: "slow down" }],
    [422, { detail: "a string where a list was expected" }],
    [409, { outcome: "SOME_NEW_OUTCOME", detail: "x" }],
  ])("a %i that is none of the above is unknown and carries its status", async (status, body) => {
    answer(status, body);

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "unknown", missing: [], status });
  });

  it("a 500 whose body is not JSON is unknown too", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 500,
          json: () => Promise.reject(new SyntaxError("Unexpected token <")),
        } as unknown as Response),
      ),
    );

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "unknown", missing: [], status: 500 });
  });

  it("a 401 is unauthorized and clears nothing else of the result", async () => {
    answer(401, { detail: "Not authenticated" });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "unauthorized" });
  });
});

describe("saveCredential, what it never does", () => {
  it("resolves, never rejects, when fetch throws a plain Error", async () => {
    failToConnect(new Error(`boom ${K} ${S}`));

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "noAnswer", missing: [], status: 0 });
  });

  it("resolves noAnswer, never rejects, when the connection dies while a 200's body is read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.reject(new TypeError(`network error while reading ${K}`)),
        } as unknown as Response),
      ),
    );

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "noAnswer", missing: [], status: 0 });
  });

  it.each([
    ["a 500", () => answer(500, { detail: "broken" })],
    ["no answer", () => failToConnect()],
    ["a 422 refusal", () => answer(422, { outcome: "KEY_REJECTED", detail: "no" })],
    ["a 409 refusal", () => answer(409, { outcome: "CONCURRENT_SAVE", detail: "no" })],
  ])("test_a_failed_save_is_not_retried: %s is one request", async (_label, stub) => {
    const fetchMock = stub();

    await saveCredential("bybit", K, S, []);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends one PUT to the exchange's path with the key and the secret only in its body, for Bybit", async () => {
    const fetchMock = answer(200, SAVED_BODY);

    await saveCredential("bybit", K, S, []);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/api/credentials/bybit`);
    expect(url).not.toContain(K);
    expect(url).not.toContain(S);
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ api_key: K, api_secret: S });
  });

  it("adds each confirmation as true for Binance, and no label", async () => {
    const fetchMock = answer(200, SAVED_BODY);

    await saveCredential("binance", K, S, ["withdrawals_disabled_confirmed", "futures_enabled_confirmed"]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/api/credentials/binance`);
    const sent = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(sent).toEqual({
      api_key: K,
      api_secret: S,
      withdrawals_disabled_confirmed: true,
      futures_enabled_confirmed: true,
    });
    expect(Object.keys(sent)).not.toContain("label");
  });

  it("test_a_save_result_is_a_plain_object_of_known_fields", async () => {
    const echo = `${K}${S}`;
    const known = new Set(["kind", "last4", "readOnly", "reason", "missing", "status"]);
    const answers: [number, unknown][] = [
      [200, { ...SAVED_BODY, detail: echo, input: K, api_key: K, api_secret: S }],
      [422, { outcome: "KEY_REJECTED", detail: echo, input: S }],
      [422, { outcome: "CONFIRMATION_REQUIRED", detail: echo, missing: ["futures_enabled_confirmed"] }],
      [422, { detail: [{ type: "string_too_short", loc: ["body", "api_key"], msg: "short", input: K }] }],
      [500, { detail: echo }],
      [404, { detail: echo }],
    ];

    for (const [status, body] of answers) {
      answer(status, body);
      const result: SaveResult = await saveCredential("bybit", K, S, []);

      expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
      expect(Object.keys(result).length).toBeGreaterThan(0);
      for (const key of Object.keys(result)) {
        expect(known.has(key)).toBe(true);
      }
      expect(JSON.stringify(result)).not.toContain(K);
      expect(JSON.stringify(result)).not.toContain(S);
    }
  });
});

// ---- The delete (design § G; task 13.6.2) ----

const DETAIL = "SERVER-DETAIL-SENTINEL: the text the server wrote";

const FULL_REFUSAL = {
  outcome: "EXCHANGE_NOT_FLAT",
  detail: DETAIL,
  enabled_strategies: [
    { id: "s-1", name: "Alpha" },
    { id: "s-2", name: "Beta" },
  ],
  symbols: ["STXUSDT.P", "BTCUSDT"],
  allocations: ["a-1", "a-2", "a-3"],
  live_reservations: [],
  in_flight_attempts: ["x-1"],
  open_discrepancies: ["ETHUSDT"],
};

function expectOneDeleteTo(fetchMock: ReturnType<typeof answer>, exchange: string) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe(`${API_BASE_URL}/api/credentials/${exchange}`);
  expect(init.method).toBe("DELETE");
  expect(init.body).toBeUndefined();
}

describe("deleteCredential, the request", () => {
  it("sends one DELETE to the exchange's path with no body, and nothing else", async () => {
    const fetchMock = answer(200, { exchange: "bybit" });

    await deleteCredential("bybit");

    expectOneDeleteTo(fetchMock, "bybit");
  });

  it("reads a 200 as deleted whatever the body says", async () => {
    answer(200, { exchange: "bybit", detail: DETAIL });

    expect(await deleteCredential("bybit")).toEqual({ kind: "deleted" });
  });

  it("reads a 204 with no body as deleted", async () => {
    answer(204, undefined);

    expect(await deleteCredential("binance")).toEqual({ kind: "deleted" });
  });

  it("reads a 200 whose body is not JSON as unknown: the panel cannot tell what answered", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError("<html>")) } as unknown as Response),
      ),
    );

    expect(await deleteCredential("bybit")).toEqual({ kind: "unknown" });
  });
});

describe("deleteCredential, a refusal and its lists", () => {
  it("reads the lists of a 409 EXCHANGE_NOT_FLAT: names, symbols as sent, the rest counted", async () => {
    answer(409, FULL_REFUSAL);

    expect(await deleteCredential("bybit")).toEqual({
      kind: "notFlat",
      lists: {
        enabledStrategies: ["Alpha", "Beta"],
        symbols: ["STXUSDT.P", "BTCUSDT"],
        allocations: 3,
        liveReservations: 0,
        inFlightAttempts: 1,
        openDiscrepancies: ["ETHUSDT"],
      },
    });
  });

  it("keeps empty lists as zero, so the dialog can leave their line out", async () => {
    answer(409, {
      ...FULL_REFUSAL,
      enabled_strategies: [],
      symbols: [],
      allocations: [],
      in_flight_attempts: [],
      open_discrepancies: [],
    });

    expect(await deleteCredential("bybit")).toEqual({
      kind: "notFlat",
      lists: {
        enabledStrategies: [],
        symbols: [],
        allocations: 0,
        liveReservations: 0,
        inFlightAttempts: 0,
        openDiscrepancies: [],
      },
    });
  });

  it("reads a refusal without open_discrepancies as none: a bundle can reach production before the API's pull", async () => {
    const { open_discrepancies: _absent, ...older } = FULL_REFUSAL;
    answer(409, older);

    expect(await deleteCredential("bybit")).toEqual({
      kind: "notFlat",
      lists: {
        enabledStrategies: ["Alpha", "Beta"],
        symbols: ["STXUSDT.P", "BTCUSDT"],
        allocations: 3,
        liveReservations: 0,
        inFlightAttempts: 1,
        openDiscrepancies: [],
      },
    });
  });

  it.each([
    ["not a list", "a string"],
    ["a list with an entry that is not text", ["ETHUSDT", 5]],
  ])("never half a list: open_discrepancies that is %s makes the whole refusal unlisted", async (_label, value) => {
    answer(409, { ...FULL_REFUSAL, open_discrepancies: value });

    expect(await deleteCredential("bybit")).toEqual({ kind: "notFlat", lists: null });
  });

  it.each([
    "enabled_strategies",
    "symbols",
    "allocations",
    "live_reservations",
    "in_flight_attempts",
  ])("never half a list: a missing %s makes the whole refusal unlisted", async (field) => {
    const { [field]: _gone, ...body } = FULL_REFUSAL as Record<string, unknown>;
    answer(409, body);

    expect(await deleteCredential("bybit")).toEqual({ kind: "notFlat", lists: null });
  });

  it.each([
    "enabled_strategies",
    "symbols",
    "allocations",
    "live_reservations",
    "in_flight_attempts",
  ])("never half a list: %s that is not a list makes the whole refusal unlisted", async (field) => {
    answer(409, { ...FULL_REFUSAL, [field]: "a string" });

    expect(await deleteCredential("bybit")).toEqual({ kind: "notFlat", lists: null });
  });

  it.each([
    ["an entry with no name", [{ id: "s-1" }]],
    ["an entry whose name is empty", [{ id: "s-1", name: "" }]],
    ["an entry whose name is not text", [{ id: "s-1", name: 7 }]],
    ["an entry that is not an object", ["Alpha"]],
    ["one good entry and one with no name", [{ id: "s-1", name: "Alpha" }, { id: "s-2" }]],
  ])("never half a list: %s makes the whole refusal unlisted", async (_label, strategies) => {
    answer(409, { ...FULL_REFUSAL, enabled_strategies: strategies });

    expect(await deleteCredential("bybit")).toEqual({ kind: "notFlat", lists: null });
  });

  it.each([
    ["symbols", ["STXUSDT.P", 5]],
    ["allocations", ["a-1", null]],
    ["live_reservations", [{}]],
    ["in_flight_attempts", [1]],
  ])("never half a list: a %s entry that is not text makes the whole refusal unlisted", async (field, entries) => {
    answer(409, { ...FULL_REFUSAL, [field]: entries });

    expect(await deleteCredential("bybit")).toEqual({ kind: "notFlat", lists: null });
  });

  it("reads a 409 with another outcome, or none, as unknown: it is not the refusal the panel knows", async () => {
    answer(409, { outcome: "CONCURRENT_SAVE", detail: DETAIL });
    expect(await deleteCredential("bybit")).toEqual({ kind: "unknown" });

    answer(409, undefined);
    expect(await deleteCredential("bybit")).toEqual({ kind: "unknown" });
  });
});

describe("deleteCredential, the other answers", () => {
  it("reads a 404 as gone, never as a success", async () => {
    answer(404, { detail: "no key" });

    expect(await deleteCredential("bybit")).toEqual({ kind: "gone" });
  });

  it("leaves a 401 to the token gate", async () => {
    answer(401, { detail: "no" });

    expect(await deleteCredential("bybit")).toEqual({ kind: "unauthorized" });
  });

  it.each([
    ["a 500", () => answer(500, { detail: DETAIL })],
    ["a 503", () => answer(503, { detail: DETAIL })],
    ["a 422", () => answer(422, { detail: [{ loc: ["path"], msg: "x" }] })],
    ["no answer", () => failToConnect()],
    ["a plain Error", () => failToConnect(new Error("boom"))],
  ])("reads %s as unknown", async (_label, stub) => {
    stub();

    expect(await deleteCredential("bybit")).toEqual({ kind: "unknown" });
  });

  it.each([
    ["a 200", () => answer(200, {})],
    ["a 409", () => answer(409, FULL_REFUSAL)],
    ["a 404", () => answer(404, {})],
    ["a 500", () => answer(500, {})],
    ["no answer", () => failToConnect()],
  ])("never retries: %s is one request", async (_label, stub) => {
    const fetchMock = stub();

    await deleteCredential("bybit");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("resolves a plain object of known fields that never holds the server's wording", async () => {
    const known = new Set([
      "kind",
      "lists",
      "enabledStrategies",
      "symbols",
      "allocations",
      "liveReservations",
      "inFlightAttempts",
      "openDiscrepancies",
    ]);
    const answers: [number, unknown][] = [
      [200, { detail: DETAIL }],
      [409, FULL_REFUSAL],
      [409, { ...FULL_REFUSAL, symbols: 3 }],
      [404, { detail: DETAIL }],
      [500, { detail: DETAIL }],
    ];

    for (const [status, body] of answers) {
      answer(status, body);
      const result: DeleteResult = await deleteCredential("bybit");

      expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
      expect(JSON.stringify(result)).not.toContain(DETAIL);
      for (const key of Object.keys(result)) expect(known.has(key)).toBe(true);
    }
  });
});

function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response;
}

/**
 * Credentials and pools are read once and answered at once; the DELETE is answered by `onDelete`, and every read
 * after it by `afterwards` (a read the test holds open, say). `log` is every request, in the order it was sent.
 */
function session(onDelete: () => Promise<Response>, afterwards: (path: string) => Promise<Response>) {
  const log: string[] = [];
  let deleted = false;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(input).replace(`${API_BASE_URL}/api`, "");
    log.push(`${method} ${path}`);
    if (method === "DELETE") {
      deleted = true;
      return onDelete();
    }
    if (deleted) return afterwards(path);
    return Promise.resolve(reply(200, []));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { log, fetchMock };
}

function mountHooks() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  const hook = renderHook(
    () => ({ credentials: useCredentials(), pools: usePools(), remove: useDeleteCredential() }),
    { wrapper },
  );
  return { client, hook };
}

async function readsDone(hook: ReturnType<typeof mountHooks>["hook"]) {
  await waitFor(() => {
    expect(hook.result.current.credentials.isSuccess).toBe(true);
    expect(hook.result.current.pools.isSuccess).toBe(true);
  });
}

describe("useDeleteCredential", () => {
  it("sends the exchange id and nothing else, and reports the result", async () => {
    const { log, fetchMock } = session(() => Promise.resolve(reply(200, {})), () => Promise.resolve(reply(200, [])));
    const { hook } = mountHooks();
    await readsDone(hook);

    let result: DeleteResult | undefined;
    await act(async () => {
      result = await hook.result.current.remove.mutateAsync("bybit");
    });

    expect(result).toEqual({ kind: "deleted" });
    expect(log.filter((line) => line.startsWith("DELETE"))).toEqual(["DELETE /credentials/bybit"]);
    const deletes = fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect((deletes[0]?.[1] as RequestInit).body).toBeUndefined();
  });

  it("test_deleting_leaves_no_secret_in_any_cache: the variables are the exchange id, and no cache holds what the server wrote", async () => {
    session(() => Promise.resolve(reply(409, FULL_REFUSAL)), () => Promise.resolve(reply(200, [])));
    const { client, hook } = mountHooks();
    await readsDone(hook);

    await act(async () => {
      await hook.result.current.remove.mutateAsync("bybit");
    });

    const mutations = client.getMutationCache().getAll();
    expect(mutations.length).toBeGreaterThan(0);
    for (const mutation of mutations) {
      expect(mutation.state.variables).toBe("bybit");
      expect(JSON.stringify([mutation.state.data, mutation.state.error])).not.toContain(DETAIL);
      expect(JSON.stringify([mutation.state.data, mutation.state.error])).not.toContain(K);
      expect(JSON.stringify([mutation.state.data, mutation.state.error])).not.toContain(S);
    }
    for (const query of client.getQueryCache().getAll()) {
      const held = JSON.stringify([query.queryKey, query.state.data, query.state.error?.message]);
      expect(held).not.toContain(DETAIL);
      expect(held).not.toContain(K);
      expect(held).not.toContain(S);
    }
  });

  it.each([
    ["a delete that worked", () => reply(200, {})],
    ["a refusal", () => reply(409, FULL_REFUSAL)],
    ["a 404", () => reply(404, {})],
    ["a 500", () => reply(500, {})],
  ])("after %s, reads both lists again and reports only when both are read", async (_label, answerOf) => {
    const credentials = deferred();
    const pools = deferred();
    const { log } = session(
      () => Promise.resolve(answerOf()),
      (path) => (path === "/credentials" ? credentials.promise : pools.promise),
    );
    const { hook } = mountHooks();
    await readsDone(hook);
    const before = log.length;

    let settled = false;
    let reported: Promise<DeleteResult> | undefined;
    await act(async () => {
      reported = hook.result.current.remove.mutateAsync("bybit").then((result) => {
        settled = true;
        return result;
      });
    });

    await waitFor(() => expect(log.length).toBe(before + 3));
    expect(log[before]).toBe("DELETE /credentials/bybit");
    expect(log.slice(before + 1).sort()).toEqual(["GET /credentials", "GET /pools"]);
    // Both reads are held open: the mutation has not reported.
    expect(settled).toBe(false);

    credentials.resolve(reply(200, []));
    await act(async () => {
      await Promise.resolve();
    });
    expect(settled).toBe(false);

    pools.resolve(reply(200, []));
    await act(async () => {
      await reported;
    });
    expect(settled).toBe(true);
  });

  it("reads both lists again after the hook has left the document: the re-read does not depend on a mounted caller", async () => {
    const release = deferred();
    const { log } = session(() => release.promise, () => Promise.resolve(reply(200, [])));
    const { hook } = mountHooks();
    await readsDone(hook);
    const before = log.length;

    act(() => {
      hook.result.current.remove.mutate("bybit");
    });
    await waitFor(() => expect(log[before]).toBe("DELETE /credentials/bybit"));
    hook.unmount();
    release.resolve(reply(200, {}));

    await waitFor(() => expect(log.slice(before + 1).sort()).toEqual(["GET /credentials", "GET /pools"]));
  });

  it("leaves a 401 to the token gate: no list is read again", async () => {
    const { log } = session(() => Promise.resolve(reply(401, {})), () => Promise.resolve(reply(200, [])));
    const { hook } = mountHooks();
    await readsDone(hook);
    const before = log.length;

    await act(async () => {
      await hook.result.current.remove.mutateAsync("bybit");
    });

    expect(log.slice(before)).toEqual(["DELETE /credentials/bybit"]);
  });

  it("does not retry a failed delete", async () => {
    const { log } = session(() => Promise.resolve(reply(500, {})), () => Promise.resolve(reply(200, [])));
    const { hook } = mountHooks();
    await readsDone(hook);

    await act(async () => {
      await hook.result.current.remove.mutateAsync("bybit");
    });

    expect(log.filter((line) => line.startsWith("DELETE"))).toHaveLength(1);
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
