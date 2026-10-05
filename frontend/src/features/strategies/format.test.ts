import { describe, expect, it } from "vitest";

import { figureText } from "@/features/strategies/format";

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
