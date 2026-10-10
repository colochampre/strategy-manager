import { describe, expect, it } from "vitest";

import { handlePosition, parseDraft, readStored, roundToHandle } from "@/features/strategies/share-value";

// The share is one decimal string. Nothing is added, multiplied or converted; the only arithmetic is
// the handle's rounding and its position on the track (design § C, § O).

describe("readStored", () => {
  it.each([
    ["33.50", "33.5"],
    ["100.000", "100"],
    ["0.5", "0.5"],
    ["0.50", "0.5"],
    ["33.5", "33.5"],
    ["7", "7"],
    ["007.250", "7.25"],
  ])("reads a stored share into its canonical form: %s", (stored, canonical) => {
    expect(readStored(stored)).toBe(canonical);
  });

  it.each(["1E-7", "+5", "-5", "", "33.", ".5", "33,5", " 33.5", "abc"])(
    "a stored text that is not a plain decimal is unreadable: %j",
    (stored) => {
      expect(readStored(stored)).toBeNull();
    },
  );
});

describe("parseDraft", () => {
  it("reads one comma as a decimal separator", () => {
    expect(parseDraft("33,5")).toEqual({ valid: true, canonical: "33.5" });
    expect(parseDraft("0,5")).toEqual({ valid: true, canonical: "0.5" });
  });

  it.each(["0", "0.0", "0,00"])("zero is not above 0: %j", (text) => {
    expect(parseDraft(text)).toEqual({ valid: false, refusal: "not-above-zero" });
  });

  it.each(["100.5", "150", "1000", "100.000000000000000001"])("%j is above 100", (text) => {
    expect(parseDraft(text)).toEqual({ valid: false, refusal: "above-hundred" });
  });

  it.each(["100", "100.0", "99.999"])("%j is at most 100 and valid", (text) => {
    expect(parseDraft(text)).toMatchObject({ valid: true });
  });

  it.each([
    "",
    "abc",
    "1e1",
    "-5",
    "25%",
    "1.000,5",
    "33.",
    ".5",
    "33,",
    "3,3,5",
    "٣٣",
    "３３",
    " 33.5",
    "33.5 ",
    "33 .5",
  ])("not a number is not a value, and nothing is trimmed into one: %j", (text) => {
    expect(parseDraft(text)).toEqual({ valid: false, refusal: "not-a-number" });
  });

  // Owner decision 50: the API refuses a share of more than 18 decimal places, judged on the canonical
  // form, because that is what the panel sends.
  it.each(["0.1234567890123456789", "33.3333333333333333333", "99.9999999999999999999"])(
    "more than 18 decimal places is refused: %j",
    (text) => {
      expect(parseDraft(text)).toEqual({ valid: false, refusal: "too-many-decimals" });
    },
  );

  it("18 decimal places is the longest valid share", () => {
    expect(parseDraft("0.123456789012345678")).toEqual({ valid: true, canonical: "0.123456789012345678" });
  });

  it("the bound is judged on the canonical form, so trailing zeros do not count", () => {
    expect(parseDraft("1.5000000000000000000")).toEqual({ valid: true, canonical: "1.5" });
    expect(parseDraft("1,5000000000000000000")).toEqual({ valid: true, canonical: "1.5" });
  });

  it("the earlier refusals come first: zero, above 100, then too many decimals", () => {
    expect(parseDraft("0.0000000000000000000")).toEqual({ valid: false, refusal: "not-above-zero" });
    expect(parseDraft("100.0000000000000000001")).toEqual({ valid: false, refusal: "above-hundred" });
    expect(parseDraft("abc.0000000000000000001")).toEqual({ valid: false, refusal: "not-a-number" });
  });

  it.each([
    ["007", "7"],
    ["0033.50", "33.5"],
    ["0.50", "0.5"],
  ])("leading zeros change no value: %s", (text, canonical) => {
    expect(parseDraft(text)).toEqual({ valid: true, canonical });
  });

  it.each([
    ["0.5", "0.5"],
    ["100", "100"],
  ])("%s is valid", (text, canonical) => {
    expect(parseDraft(text)).toEqual({ valid: true, canonical });
  });

  it.each([
    ["33.50", "33.5"],
    ["0.5", "0.5"],
    ["100.000", "100"],
    ["7.25", "7.25"],
  ])("a draft is canonical, so the stored value typed back is unchanged: %s", (stored, canonical) => {
    // Compared with the literal and with the stored reading, so neither side can drift alone.
    expect(parseDraft(stored)).toEqual({ valid: true, canonical });
    expect(readStored(stored)).toBe(canonical);
  });
});

describe("roundToHandle", () => {
  it.each([
    ["33.5", 34],
    ["0.5", 1],
    ["0.4", 1],
    ["99.5", 100],
    ["24.5", 25],
    ["100", 100],
    ["1", 1],
    ["50", 50],
    ["99.4", 99],
    ["24.49", 24],
    ["7.5", 8],
  ])("the handle is the value rounded half up and clamped from 1 to 100: %s gives %i", (canonical, handle) => {
    expect(roundToHandle(canonical)).toBe(handle);
  });
});

describe("handlePosition", () => {
  it.each([
    [1, "0%"],
    [25, "24.2424%"],
    [50, "49.4949%"],
    [75, "74.7475%"],
    [100, "100%"],
  ])("the handle's position is (v - 1) / 99: %i gives %s", (step, position) => {
    expect(handlePosition(step)).toBe(position);
  });
});
