import { describe, expect, it } from "vitest";

import type { CredentialEntry } from "@/shared/api/credentials";
import { exchangeList, keyMark, keyState, knownPools, poolOn } from "@/shared/credentials/key-state";
import { emptyKey, pool, storedKey } from "@/test/harness";

/** The harness builders answer in the API's wire shape; the module takes the typed entry. */
function stored(overrides: Record<string, unknown> = {}): CredentialEntry {
  return storedKey("bybit", overrides) as unknown as CredentialEntry;
}

function empty(): CredentialEntry {
  return emptyKey("bybit") as unknown as CredentialEntry;
}

function disabled(exchange: string, venue = "usdt-m") {
  return { ...pool(exchange, venue), enabled: false };
}

describe("keyState: every row of design § B", () => {
  it.each([
    ["a stored key that can trade, whatever the pools", stored(), true, "key"],
    ["a stored key that can trade, no pool on", stored(), false, "key"],
    ["a stored key that can trade, pools unknown", stored(), null, "key"],
    ["a stored key that cannot trade, a pool on", stored({ trade_capable: false }), true, "readOnly"],
    ["a stored key that cannot trade, no pool on", stored({ trade_capable: false }), false, "readOnly"],
    ["a stored key that cannot trade, pools unknown", stored({ trade_capable: false }), null, "readOnly"],
    ["an EMPTY entry with a pool on", empty(), true, "degraded"],
    ["no entry with a pool on", undefined, true, "degraded"],
    ["an EMPTY entry with no pool on", empty(), false, "empty"],
    ["no entry with no pool on", undefined, false, "empty"],
    ["an EMPTY entry with the pools unknown", empty(), null, "empty"],
    ["no entry with the pools unknown", undefined, null, "empty"],
  ] as const)("%s", (_label, entry, on, expected) => {
    expect(keyState(entry, on)).toBe(expected);
  });

  it("gives an EMPTY entry and a missing entry the same state, for every pool answer", () => {
    for (const on of [true, false, null] as const) {
      expect(keyState(empty(), on)).toBe(keyState(undefined, on));
    }
  });
});

describe("keyMark: the word and the tone of each state", () => {
  it.each([
    ["readOnly", { word: "readOnly", tone: "amber" }],
    ["degraded", { word: "noKey", tone: "amber" }],
    ["empty", { word: "noKey", tone: "neutral" }],
    ["key", null],
  ] as const)("the state %s", (state, expected) => {
    expect(keyMark(state)).toEqual(expected);
  });
});

describe("poolOn: an exchange has a pool on when any enabled pool is its own", () => {
  it("counts any enabled pool of THAT exchange", () => {
    expect(poolOn("bybit", [disabled("bybit", "spot"), pool("bybit", "usdt-m")])).toBe(true);
  });

  it("does not count a disabled pool of that exchange", () => {
    expect(poolOn("bybit", [disabled("bybit")])).toBe(false);
  });

  it("does not count another exchange's pool", () => {
    expect(poolOn("binance", [pool("bybit"), pool("pionex")])).toBe(false);
  });

  it("is false for an exchange with no pool in a list that was read", () => {
    expect(poolOn("binance", [])).toBe(false);
  });

  it("is unknown, never false, while the pools are not known", () => {
    expect(poolOn("bybit", undefined)).toBeNull();
  });
});

describe("knownPools: the one rule for when the pools may be believed (task 13.5.0)", () => {
  const list = [pool("bybit")];

  it("gives the list of a read that succeeded", () => {
    expect(knownPools({ status: "success", data: list })).toBe(list);
  });

  it("gives nothing for a read that failed, even when an earlier list is still held", () => {
    expect(knownPools({ status: "error", data: list })).toBeUndefined();
  });

  it("gives nothing while the first read is pending", () => {
    expect(knownPools({ status: "pending", data: undefined })).toBeUndefined();
  });
});

describe("exchangeList: the exchanges of the page, without repeats", () => {
  const served = ["bybit", "binance"];

  it("lists the served ids in the file's order, not sorted", () => {
    expect(exchangeList(served, [], [])).toEqual(["bybit", "binance"]);
    expect(exchangeList(["binance", "bybit"], [], [])).toEqual(["binance", "bybit"]);
  });

  it("lists Binance when neither route mentions it", () => {
    const list = exchangeList(served, [storedKey("bybit") as { exchange: string }], [pool("bybit")]);
    expect(list).toContain("binance");
  });

  it("puts the other exchanges of the credentials after the served ones, sorted by name", () => {
    const entries = ["zeta", "bybit", "alpha"].map((name) => ({ exchange: name }));
    expect(exchangeList(served, entries, [])).toEqual(["bybit", "binance", "alpha", "zeta"]);
  });

  it("puts the exchanges that only have a pool last, sorted by name, after those of the credentials", () => {
    const entries = [{ exchange: "zeta" }];
    const pools = [pool("pionex"), pool("bybit"), pool("mexc"), pool("zeta"), pool("alpha")];
    // The credentials' extras come first even though "zeta" sorts after "alpha" and "mexc".
    expect(exchangeList(served, entries, pools)).toEqual(["bybit", "binance", "zeta", "alpha", "mexc", "pionex"]);
  });

  it("lists Pionex when only the pools mention it", () => {
    expect(exchangeList(served, [], [pool("pionex", "spot"), pool("pionex", "usdt-m")])).toEqual([
      "bybit",
      "binance",
      "pionex",
    ]);
  });

  it("never repeats an exchange that two sources or two pools name", () => {
    const entries = [{ exchange: "pionex" }, { exchange: "bybit" }];
    const pools = [pool("pionex", "spot"), pool("pionex", "usdt-m"), pool("binance")];
    expect(exchangeList(served, entries, pools)).toEqual(["bybit", "binance", "pionex"]);
  });
});
