import { describe, expect, it } from "vitest";

import { orderPools } from "@/features/overview/poolOrder";
import type { Pool } from "@/shared/api/types";

function make(venue: string, currency: string, available: string | null, enabled = true): Pool {
  return {
    exchange: "pionex",
    venue,
    settlement_currency: currency,
    enabled,
    balance:
      available === null
        ? null
        : { total: available, available, observed_at: "2026-09-30T10:00:00+00:00", stale: false },
    reserved: "0",
    allocatable: available,
  };
}

function names(pools: readonly Pool[]): string[] {
  return pools.map((pool) => `${pool.venue}/${pool.settlement_currency}`);
}

describe("orderPools", () => {
  it("puts enabled pools before disabled ones, whatever their currency or balance", () => {
    const ordered = orderPools([
      make("spot", "USDT", "9000", false),
      make("coin-m", "BTC", "0.5", true),
      make("usdt-m", "USDT", "10", true),
    ]);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "coin-m/BTC", "spot/USDT"]);
  });

  it("puts USDT pools before other currencies, the larger available balance first", () => {
    const ordered = orderPools([
      make("coin-m", "BTC", "0.5"),
      make("spot", "USDT", "120.50"),
      make("usdt-m", "USDT", "999.99"),
    ]);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "spot/USDT", "coin-m/BTC"]);
  });

  it("compares balances as numbers, not as text", () => {
    const ordered = orderPools([make("spot", "USDT", "99.00"), make("usdt-m", "USDT", "1000.00")]);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "spot/USDT"]);
  });

  it("puts a USDT pool nothing has synced after the USDT pools that have a balance", () => {
    const ordered = orderPools([make("spot", "USDT", null), make("usdt-m", "USDT", "0")]);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "spot/USDT"]);
  });

  it("orders the remaining pools by currency code, never by their balance", () => {
    const ordered = orderPools([
      make("coin-m", "ETH", "900"),
      make("coin-m", "BTC", "0.001"),
      make("coin-m", "SOL", "50"),
    ]);
    expect(names(ordered)).toEqual(["coin-m/BTC", "coin-m/ETH", "coin-m/SOL"]);
  });

  it("orders Pionex's real shape: enabled first, then USDT, then BTC before ETH", () => {
    const ordered = orderPools([
      make("coin-m", "ETH", "4", false),
      make("coin-m", "BTC", "1", false),
      make("spot", "USDT", "300", false),
    ]);
    expect(names(ordered)).toEqual(["spot/USDT", "coin-m/BTC", "coin-m/ETH"]);
  });

  it("never merges or sums pools: the same number of pools comes back, each untouched", () => {
    const input = [make("usdt-m", "USDT", "100"), make("spot", "USDT", "200"), make("coin-m", "BTC", "1")];
    const ordered = orderPools(input);
    expect(ordered).toHaveLength(3);
    expect(new Set(ordered)).toEqual(new Set(input));
    // Two USDT pools are ranked by their OWN balance: their sum (300) would tie them at 300 each.
    expect(names(ordered).slice(0, 2)).toEqual(["spot/USDT", "usdt-m/USDT"]);
  });

  it("keeps the server's order between equals", () => {
    const input = [make("b", "USDT", "5"), make("a", "USDT", "5")];
    expect(names(orderPools(input))).toEqual(["b/USDT", "a/USDT"]);
  });

  it("returns a new list and leaves its input in the order it came in", () => {
    const input = [make("spot", "USDT", "1"), make("usdt-m", "USDT", "2")];
    const ordered = orderPools(input);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "spot/USDT"]);
    expect(ordered).not.toBe(input);
    expect(names(input)).toEqual(["spot/USDT", "usdt-m/USDT"]);
  });

  it("puts an unreadable balance last among USDT pools instead of ranking it", () => {
    const broken = make("spot", "USDT", "abc");
    const ordered = orderPools([broken, make("usdt-m", "USDT", "1")]);
    expect(names(ordered)).toEqual(["usdt-m/USDT", "spot/USDT"]);
  });
});
