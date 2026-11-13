import { describe, expect, it } from "vitest";

import { maxLeverage, readStopLevel } from "@/features/strategies/stop-level";

describe("readStopLevel", () => {
  it.each([
    ["1", "1"],
    ["10", "10"],
    ["7.5", "7.5"],
    ["12.34", "12.34"],
    ["50", "50"],
    ["  10  ", "10"],
    ["07.50", "7.5"],
    ["7.500", "7.5"],
    ["50.00", "50"],
  ])("%j is the level %j", (text, canonical) => {
    expect(readStopLevel(text)).toEqual({ valid: true, canonical });
  });

  it.each(["0.5", "0", "0.99", "50.01", "60", "100", "99999999999999999999"])("%j is out of range", (text) => {
    expect(readStopLevel(text)).toEqual({ valid: false, refusal: "out-of-range" });
  });

  it.each(["7.505", "10.001"])("%j has more than two decimals", (text) => {
    expect(readStopLevel(text)).toEqual({ valid: false, refusal: "too-many-decimals" });
  });

  it.each(["", "  ", "abc", "-5", "+5", "7,5", "1e1", "5%", ".5", "5."])("%j is not a number", (text) => {
    expect(readStopLevel(text)).toEqual({ valid: false, refusal: "not-a-number" });
  });
});

describe("maxLeverage", () => {
  it.each([
    ["10", 9],
    ["10.00", 9],
    ["5", 16],
    ["1", 20],
    ["4", 20],
    ["4.76", 17],
    ["7.5", 11],
    ["15", 6],
    ["50", 1],
  ])("a stop of %s caps leverage at %i", (level, cap) => {
    expect(maxLeverage(level)).toBe(cap);
  });

  it("is the plain ceiling when there is no level, or the level is not one", () => {
    expect(maxLeverage(undefined)).toBe(20);
    expect(maxLeverage("abc")).toBe(20);
    expect(maxLeverage("60")).toBe(20);
  });
});
