import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchStrategyPerformance } from "@/shared/api/performance";
import { emptyPerformance, lock, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function respond(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL) =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response),
    ),
  );
}

function entry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { pair: "SOLUSDT", trades: 3, wins: 2, win_rate: "0.6666666667", pnl: "4.20", return: null, ...overrides };
}

function without(key: string): Record<string, unknown> {
  const { [key]: _removed, ...rest } = entry();
  return rest;
}

function report(byPair: unknown[]) {
  return { ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: byPair };
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchStrategyPerformance by_pair win fields", () => {
  it("accepts an entry with the two new fields", async () => {
    respond(report([entry()]));

    const body = await fetchStrategyPerformance(ID);

    expect(body?.by_pair).toEqual([entry()]);
  });

  it("refuses a by_pair entry lacking wins", async () => {
    respond(report([without("wins")]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a by_pair entry lacking win_rate", async () => {
    respond(report([without("win_rate")]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["a fraction", 1.5],
    ["a string", "3"],
    ["null", null],
  ])("refuses wins that is not an integer (%s)", async (_name, wins) => {
    respond(report([entry({ wins })]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["below zero", -1],
    ["above trades", 4],
  ])("refuses wins %s", async (_name, wins) => {
    respond(report([entry({ wins })]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("accepts wins at both ends of its range", async () => {
    respond(report([entry({ wins: 0, win_rate: "0.0000000000" }), entry({ pair: "ETHUSDT", wins: 3, win_rate: "1.0000000000" })]));

    const body = await fetchStrategyPerformance(ID);

    expect(body?.by_pair.map((pair) => pair.wins)).toEqual([0, 3]);
  });

  it("refuses a win_rate that is a JSON number", async () => {
    respond(report([entry({ win_rate: 0.6666666667 })]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses a body of the four old fields, and so the whole report", async () => {
    respond(report([{ pair: "SOLUSDT", trades: 3, pnl: "4.20", return: null }]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("one bad entry among good ones refuses the lot", async () => {
    respond(report([entry(), entry({ pair: "ETHUSDT", wins: 9 }), entry({ pair: "BTCUSDT" })]));

    await expect(fetchStrategyPerformance(ID)).rejects.toBeInstanceOf(ApiError);
  });
});
