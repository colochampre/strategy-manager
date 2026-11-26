import { describe, expect, it } from "vitest";

import { percentText } from "@/shared/lib/amount-text";

// Every percentage of the app is written joined to its sign, "+80,8%" and not "+80,8 %", in every language (L43).
describe("percentText", () => {
  it("joins the sign to the number in Spanish, which Intl writes with a no-break space", () => {
    expect(percentText(0.808, "es")).toBe("+80,8%");
    expect(percentText(-0.139, "es")).toBe("-13,9%");
    expect(percentText(0, "es")).toBe("0,0%");
  });

  it("writes English as it always did", () => {
    expect(percentText(0.808, "en")).toBe("+80.8%");
    expect(percentText(-0.139, "en")).toBe("-13.9%");
  });

  it("returns the number alone without the symbol, in both languages", () => {
    expect(percentText(0.808, "es", false)).toBe("+80,8");
    expect(percentText(0.808, "en", false)).toBe("+80.8");
  });
});
