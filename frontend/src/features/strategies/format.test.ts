import { describe, expect, it } from "vitest";

import { clockText, compactDateText, figureText, rateText, tableFigureText } from "@/features/strategies/format";

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

// The table's own, shorter figure (owner decision 46): at most five decimals and no trailing zeros, and four
// significant digits when five decimals would leave fewer, so a small price never reads 0. A text
// operation over the server's string with the rounding of figureText; figureText itself is unchanged.
describe("tableFigureText", () => {
  it.each([
    ["0.705295610000000000", "0.7053"],
    ["2515.952800000000000000", "2515.9528"],
    ["0.429090380000000000", "0.42909"],
    ["61250.123456000000000000", "61250.12346"],
    ["1.000000000000000000", "1"],
    ["0", "0"],
    ["0.000000000000000000", "0"],
    ["0.012345600000000000", "0.01235"],
    ["0.001234560000000000", "0.001235"],
    ["0.000005120000000000", "0.00000512"],
  ])("writes %s as %s", (stored, shown) => {
    expect(tableFigureText(stored)).toBe(shown);
  });

  it.each([
    ["0.999999", "1"],
    ["-3.250000", "-3.25"],
    ["0.000000000000000012", "0.000000000000000012"],
    ["123456789012345678901", "123456789012345678901"],
  ])("rounds, keeps the sign and never writes an exponent: %s", (stored, shown) => {
    const text = tableFigureText(stored);

    expect(text).toBe(shown);
    expect(text).not.toMatch(/e/i);
  });

  it.each(["", "x", "NaN", "Infinity", "1e3", "1.2.3", " 1", "1,5"])("gives null for a string that is not a number: %j", (stored) => {
    expect(tableFigureText(stored)).toBeNull();
  });

  it("leaves figureText as it was", () => {
    expect(figureText("0.123456789")).toBe("0.12345679");
  });
});

// Leading zeros of the integer part are text noise, not part of the number: both writers drop them
// (a regression found in review: the expression that does it lost its backslash in a refactor).
describe.each([
  ["figureText", figureText],
  ["tableFigureText", tableFigureText],
])("%s and the leading zeros of the integer part", (_name, write) => {
  it.each([
    ["007.500000000000000000", "7.5"],
    ["00.500000000000000000", "0.5"],
    ["000", "0"],
    ["000.000", "0"],
    ["0012345.678901234", "12345.678901234"],
  ])("writes %s as %s", (stored, expected) => {
    // The last case is compared with the text of the same figure without zeros, per function, since
    // each function rounds a long fraction its own way.
    const reference = stored === "0012345.678901234" ? write("12345.678901234") : expected;
    expect(write(stored)).toBe(reference);
  });

  it("gives the same text with and without leading zeros", () => {
    expect(write("0012345.678901234")).toBe(write("12345.678901234"));
    expect(write("007.5")).toBe(write("7.5"));
  });
});

// `rateText` writes the served win rate as an unsigned percentage with one decimal. It cuts first and
// formats second: a rate is never rounded up, so only a rate of exactly one reads 100.0%.

describe("rateText", () => {
  it.each([
    ["0.5833333333", "58.3%"],
    ["0.6000000000", "60.0%"],
  ])("writes a rate with one decimal and no sign: %s", (served, expected) => {
    expect(rateText(served, "en")).toBe(expected);
  });

  it.each([
    ["0.9995000000", "99.9%"],
    ["0.9950000000", "99.5%"],
  ])("cuts the rate and never rounds it up: %s", (served, expected) => {
    expect(rateText(served, "en")).toBe(expected);
  });

  it("only a rate of exactly one reads 100.0%", () => {
    expect(rateText("1.0000000000", "en")).toBe("100.0%");
    expect(rateText("0.9999999999", "en")).toBe("99.9%");
  });

  it.each([
    ["0.0000000000", "0.0%"],
    ["0.0002000000", "0.0%"],
  ])("a rate of exactly zero and one win in five thousand read 0.0%%: %s", (served, expected) => {
    expect(rateText(served, "en")).toBe(expected);
  });

  it.each(["abc", "1e-3", "", "-0.5000000000", "0.5.0"])(
    "never writes an exponent and a string that is not a plain ratio gives null: %j",
    (served) => {
      expect(rateText(served, "en")).toBeNull();
    },
  );

  it("writes the rate the way the PnL % column does in Spanish", () => {
    // Spanish writes a decimal comma and a no-break space before the sign (U+00A0), as `percentText` does.
    expect(rateText("0.5833333333", "es")).toBe("58,3 %");
    expect(rateText("1.0000000000", "es")).toBe("100,0 %");
  });
});
