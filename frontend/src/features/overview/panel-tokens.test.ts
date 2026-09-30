import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const DIR = dirname(fileURLToPath(import.meta.url));
const COMPONENTS = ["MonthlyGrid", "MonthlySummary", "LedgerLine", "RangeSelector", "PoolEyebrow"];

/** Amber is reserved for "needs your decision" (design, Colour roles); none of these is one. */
const DECISION_UTILITY = /\b(?:bg|text|border|ring|outline|fill|stroke|divide)-decision\b/;

describe("the ledger and grid components", () => {
  it("never use the amber decision colour", () => {
    for (const name of COMPONENTS) {
      const source = readFileSync(join(DIR, `${name}.tsx`), "utf8");
      expect(source.length, name).toBeGreaterThan(100);
      expect(DECISION_UTILITY.test(source), name).toBe(false);
    }
    expect(DECISION_UTILITY.test("className=\"text-decision\"")).toBe(true);
  });

  it("carry no display text of their own: every string goes through i18n", () => {
    for (const name of COMPONENTS) {
      const source = readFileSync(join(DIR, `${name}.tsx`), "utf8");
      // Drop comments, then look for words written between an opening tag and the next tag.
      const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
      const literal = /<[A-Za-z][^<>]*>\s*([A-Za-z][^<>{}]*)\s*</.exec(code);
      expect(literal?.[1], name).toBeUndefined();
    }
  });
});
