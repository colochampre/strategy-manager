import { describe, expect, it } from "vitest";

import { authoredFigures } from "@/features/strategies/card-figures";
import type { Strategy, StrategyPerformance } from "@/shared/api/types";
import { emptyPerformance } from "@/test/harness";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    subscribers: 3,
    live_subscribers: 2,
    capital: "300",
    settlement_currency: "USDT",
    ...overrides,
  } as Strategy;
}

function report(overrides: Record<string, unknown> = {}): StrategyPerformance {
  const base = emptyPerformance("bybit", "usdt-m", "USDT");
  return {
    ...base,
    strategy_id: "s",
    by_pair: [
      { pair: "ETHUSDT", trades: 4, wins: 3, win_rate: "0.75", pnl: "1", return: "0.01" },
      { pair: "BTCUSDT", trades: 6, wins: 2, win_rate: "0.3333", pnl: "1", return: "0.01" },
    ],
    trade_count: 10,
    max_drawdown: "-0.08",
    ranges: [...base.ranges.filter((entry) => entry.range !== "All"), { range: "All", pnl: "41.20", return: "0.034", trade_count: 10 }],
    ...overrides,
  } as unknown as StrategyPerformance;
}

describe("authoredFigures", () => {
  it("reads the card's figures off the author's own report", () => {
    const card = authoredFigures(strategy(), { status: "success", data: report() });
    expect(card.failed).toBe(false);
    expect(card.pnl).toBeCloseTo(41.2);
    expect(card.figures.trades).toBe(10);
    expect(card.figures.ret).toBeCloseTo(0.034);
    expect(card.figures.deepest).toBeCloseTo(-0.08);
    // Wins over closed trades across every pair: 5 of 10.
    expect(card.figures.winRate).toBeCloseTo(0.5);
    // Only those trading it live: one number on the card (L.11).
    expect(card.figures.subscribers).toBe(2);
    expect(card.figures.capital).toEqual({ amount: 300, currency: "USDT" });
  });

  it("is still reading while the report is on its way", () => {
    const card = authoredFigures(strategy(), { status: "pending", data: undefined });
    expect(card.failed).toBe(false);
    expect(card.pnl).toBeUndefined();
    expect(card.figures.trades).toBeUndefined();
    expect(card.figures.ret).toBeUndefined();
    expect(card.figures.winRate).toBeUndefined();
  });

  it("has no win rate before a trade has closed, and none of a strategy without a report", () => {
    const none = authoredFigures(strategy(), { status: "success", data: null });
    expect(none.figures.trades).toBeNull();
    expect(none.figures.ret).toBeNull();
    expect(none.figures.winRate).toBeNull();
    const flat = authoredFigures(strategy(), { status: "success", data: report({ by_pair: [] }) });
    expect(flat.figures.winRate).toBeNull();
  });

  it("fails on a failed read and on a report whose figures cannot be read", () => {
    expect(authoredFigures(strategy(), { status: "error", data: undefined }).failed).toBe(true);
    const broken = report({
      ranges: [{ range: "All", pnl: "oops", return: "0.034", trade_count: 10 }],
    });
    expect(authoredFigures(strategy(), { status: "success", data: broken }).failed).toBe(true);
  });

  it("shows no capital where the strategy holds none", () => {
    const card = authoredFigures(strategy({ capital: null }), { status: "success", data: report() });
    expect(card.figures.capital).toBeNull();
  });
});
