import { describe, expect, it } from "vitest";

import { clockText, compactDateText, figureText } from "@/features/strategies/format";

// `figureText` writes a price, a size or a fee from the server's own string. It is a text
// operation, not arithmetic: money is never computed in the browser (design § F, § 15).

describe("figureText", () => {
  it.each([
    ["0.451200000000000000", "0.4512"],
    ["1250.000000000000000000", "1250"],
    ["1.000000000000000000", "1"],
    ["0.000000000000000000", "0"],
    ["123456.789012000000000000", "123456.79"],
    ["0.63", "0.63"],
    ["0", "0"],
    ["0.123456789", "0.12345679"],
    ["999999.999", "1000000"],
    ["-3.250000", "-3.25"],
  ])("formats a stored 18-place string with up to eight significant digits and no trailing zeros: %s", (stored, shown) => {
    expect(figureText(stored)).toBe(shown);
  });

  it.each([
    ["0.000000000000000012", "0.000000000000000012"],
    ["0.000000000000000000012345678912", "0.000000000000000000012345679"],
    ["123456789012345678901", "123456789012345678901"],
  ])("never writes an exponent: %s", (stored, shown) => {
    const text = figureText(stored);

    expect(text).toBe(shown);
    expect(text).not.toMatch(/e/i);
  });

  it.each(["", "x", "NaN", "Infinity", "1e3", "1.2.3", " 1", "1,5", "--1", "0x10"])(
    "a string that is not a number gives null: %j",
    (stored) => {
      expect(figureText(stored)).toBeNull();
    },
  );
});

// The compact Opened and Closed cells of the trades table (owner decision 46): the numeric date in the
// panel's language and the 24-hour time, both read in UTC from the instant by Intl, never parsed from a
// formatted string.
describe("compactDateText", () => {
  it.each([
    ["2026-10-05T09:07:00Z", "en", "10/5/2026"],
    ["2026-10-05T09:07:00Z", "es", "5/10/2026"],
    // 01:30 UTC is still the 4th in any zone behind UTC: the date is the UTC one.
    ["2026-10-05T01:30:00Z", "en", "10/5/2026"],
    ["2026-10-05T01:30:00Z", "es", "5/10/2026"],
    ["2026-09-30T00:15:00.000001Z", "en", "9/30/2026"],
  ])("writes %s in %s as %s", (instant, locale, expected) => {
    expect(compactDateText(instant, locale)).toBe(expected);
  });

  it("returns an instant it cannot read as the server wrote it", () => {
    expect(compactDateText("not a date", "en")).toBe("not a date");
  });
});

describe("clockText", () => {
  it.each([
    ["2026-10-05T09:07:00Z", "09:07"],
    ["2026-10-05T00:05:00Z", "00:05"],
    ["2026-10-05T01:30:00Z", "01:30"],
    ["2026-09-30T23:59:59.999999Z", "23:59"],
  ])("writes %s as the 24-hour UTC time %s", (instant, expected) => {
    expect(clockText(instant)).toBe(expected);
  });

  it("gives null for an instant it cannot read", () => {
    expect(clockText("not a date")).toBeNull();
  });
});
