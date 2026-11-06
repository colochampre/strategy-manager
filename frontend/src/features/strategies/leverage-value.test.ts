import { describe, expect, it } from "vitest";

import { leveragePosition, parseLeverage } from "@/features/strategies/leverage-value";

describe("parseLeverage", () => {
  it.each([
    ["1", 1],
    ["5", 5],
    ["20", 20],
    ["  7  ", 7],
    ["05", 5],
  ])("%j is the whole number %i", (text, value) => {
    expect(parseLeverage(text)).toEqual({ valid: true, value });
  });

  it.each(["0", "00", "21", "100", "999"])("%j is a whole number out of range", (text) => {
    expect(parseLeverage(text)).toEqual({ valid: false, refusal: "out-of-range" });
  });

  it.each(["", "   ", "2.5", "2,5", "x5", "5x", "abc", "-3", "+3", "1e1", "1 0"])("%j is not a whole number", (text) => {
    expect(parseLeverage(text)).toEqual({ valid: false, refusal: "not-a-whole-number" });
  });
});

describe("leveragePosition", () => {
  it.each([
    [1, "0%"],
    [5, "21.0526%"],
    [10, "47.3684%"],
    [15, "73.6842%"],
    [20, "100%"],
  ])("step %i sits at %s of the track", (step, position) => {
    expect(leveragePosition(step)).toBe(position);
  });
});
