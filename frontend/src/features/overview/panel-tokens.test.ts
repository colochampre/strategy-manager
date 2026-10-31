import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const DIR = dirname(fileURLToPath(import.meta.url));
const COMPONENTS = [
  "MonthlyGrid",
  "MonthlySummary",
  "LedgerLine",
  "RangeSelector",
  "PoolEyebrow",
  "PoolPanel",
  "OverviewPage",
];

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

const SRC = join(DIR, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

/**
 * The design allows amber in three places: the mode badge, a read-only key and a keyless exchange (the
 * pending-bookings count left with the decision rail, owner decision 66 Q7, and nothing joined the list). The last two are drawn by
 * `shared/credentials/KeyMark.tsx`, the mark that the exchange tabs and the Settings card
 * share (PR 13, unit 13.3); the card's own border and sentence join with `ExchangeKeyCard.tsx`
 * in unit 13.4 (added to the list by the RED step of task 13.4.3, before the card uses amber). Decision 43
 * (design § F) adds the dry-run tag of a rehearsal row of the trades table, written in
 * the words and the amber of the mode badge, and the same tag on a fill of the fills table
 * whose flag differs from its operation's, and the tag in the title of the detail dialog.
 * Decision 65 adds the origin "Dry run" of an open position, written in the words and the amber
 * of the mode badge, in `features/positions/origin.ts`, the one positions file that names the class.
 */
const AMBER_ALLOWED = [
  "features/positions/origin.ts",
  "features/settings/ExchangeKeyCard.tsx",
  "features/strategies/OperationFillsTable.tsx",
  "features/strategies/TradeDetailDialog.tsx",
  "features/strategies/TradesTable.tsx",
  "shared/credentials/KeyMark.tsx",
  "shared/layout/ModeBadge.tsx",
];

describe("the amber decision colour", () => {
  it("is used only by the components the design allows", () => {
    const files = sourceFiles(SRC);
    expect(files.length).toBeGreaterThan(20);
    const users = files
      .filter((file) => DECISION_UTILITY.test(readFileSync(file, "utf8")))
      .map((file) => relative(SRC, file).replaceAll("\\", "/"))
      .sort();
    expect(users).toEqual(AMBER_ALLOWED);
  });

  it("lost the decision rail and gained nothing (spec 'The Amber Allow-List Gains Nothing')", () => {
    // Exactly the seven files below: the rail's file is not among them, and no new one is.
    expect(AMBER_ALLOWED).toEqual([
      "features/positions/origin.ts",
      "features/settings/ExchangeKeyCard.tsx",
      "features/strategies/OperationFillsTable.tsx",
      "features/strategies/TradeDetailDialog.tsx",
      "features/strategies/TradesTable.tsx",
      "shared/credentials/KeyMark.tsx",
      "shared/layout/ModeBadge.tsx",
    ]);
  });
});

/** Red (`loss`) as a colour utility, the way the amber one is matched above. */
const LOSS_UTILITY = /\b(?:bg|text|border|ring|outline|fill|stroke|divide)-loss\b/;

/**
 * Owner decision 66 Q7 (decision 65's rule): in the discrepancies unit red appears on a "Needs you" item, on the
 * navigation badge and on the venue mark, each always with its words. `ReadLine.tsx` is the page's read state,
 * which turns red only to say a read failed. A booking, a result, is never red.
 */
const RED_IN_THE_UNIT = [
  "features/discrepancies/DiscrepancyItem.tsx",
  "features/discrepancies/ReadLine.tsx",
  "features/positions/Mark.tsx",
  "features/positions/MarkLine.tsx",
  "shared/layout/NavBadge.tsx",
];

describe("red in the discrepancies unit", () => {
  const unit = sourceFiles(SRC)
    .map((file) => relative(SRC, file).replaceAll("\\", "/"))
    .filter(
      (file) =>
        file.startsWith("features/discrepancies/") ||
        file === "shared/layout/NavBadge.tsx" ||
        file.startsWith("features/positions/Mark") ||
        file === "features/positions/DiscrepancyLink.tsx" ||
        file === "features/positions/useVenueFollowUp.ts",
    );

  it("is on the item, the badge and the venue mark only", () => {
    expect(unit.length).toBeGreaterThan(8);
    const users = unit.filter((file) => LOSS_UTILITY.test(readFileSync(join(SRC, file), "utf8"))).sort();
    expect(users).toEqual(RED_IN_THE_UNIT);
    expect(LOSS_UTILITY.test('className="border-loss"')).toBe(true);
    expect(LOSS_UTILITY.test('className="border-rule"')).toBe(false);
  });

  it("never colours a booking: the booked list uses neither red nor amber", () => {
    const booked = readFileSync(join(SRC, "features/discrepancies/BookedList.tsx"), "utf8");
    expect(booked.length).toBeGreaterThan(100);
    expect(LOSS_UTILITY.test(booked)).toBe(false);
    expect(DECISION_UTILITY.test(booked)).toBe(false);
  });
});
