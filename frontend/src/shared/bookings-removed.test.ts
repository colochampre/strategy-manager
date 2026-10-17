import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/**
 * The removal pins of cd.2.22 (R18; owner decision 66 Q1; spec "The Bookings Feature Is Removed From The
 * Panel"): nothing in the panel proposes, approves or rejects a booking, so the code that did it, the keys that
 * spoke of it and the types that described it are gone, and nothing names them. A source scan in the style of
 * `shared/theme.test.ts`.
 */

const THIS_FILE = fileURLToPath(import.meta.url);
const SRC = join(dirname(THIS_FILE), "..");

function allFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return allFiles(path);
    return /\.(ts|tsx|css|json|html|svg)$/.test(entry.name) ? [path] : [];
  });
}

/** Every text file under `frontend/src` but this one, which has to spell the names it forbids. */
function scannedFiles(): string[] {
  return allFiles(SRC).filter((file) => file !== THIS_FILE);
}

/** The names of the list that a text writes, wherever it writes them: an import, a string or a comment. */
function namedIn(text: string, names: readonly string[]): string[] {
  return names.filter((name) => text.includes(name));
}

function mentions(names: readonly string[]): string[] {
  return scannedFiles().flatMap((file) =>
    namedIn(readFileSync(file, "utf8"), names).map((name) => `${relative(SRC, file).replaceAll("\\", "/")}: ${name}`),
  );
}

/** The value at a dotted path of a locale file, or undefined when any step is missing. */
function lookup(tree: unknown, path: string): unknown {
  let node: unknown = tree;
  for (const step of path.split(".")) {
    if (typeof node !== "object" || node === null || !(step in node)) return undefined;
    node = (node as Record<string, unknown>)[step];
  }
  return node;
}

describe("the bookings feature is removed from the panel", () => {
  it("names no removed hook, view, helper, rail or route in any file under frontend/src", () => {
    expect(mentions(["usePendingBookings", "BookingsListView", "pendingProposalNames", "DecisionRail", "/reconciliation/bookings"])).toEqual([]);
  });

  it("names none of the booking proposal types the panel no longer reads", () => {
    expect(mentions(["BookingProposal", "ProposedFill", "ApproveResponse", "RejectResponse", "RefusalBody"])).toEqual([]);
  });

  it.each([
    "features/bookings",
    "features/positions/pendingProposal.ts",
    "features/positions/pendingProposal.test.ts",
    "features/overview/DecisionRail.tsx",
    "features/overview/DecisionRail.test.tsx",
  ])("has no %s", (path) => {
    expect(existsSync(join(SRC, path))).toBe(false);
  });

  it.each([
    ["en", en],
    ["es", es],
  ] as const)("holds no removed key in %s.json", (_name, locale) => {
    expect(lookup(locale, "overview.decisionRail")).toBeUndefined();
    expect(lookup(locale, "positions.venue.noProposal")).toBeUndefined();
    expect(lookup(locale, "positions.venue.line.noProposal")).toBeUndefined();
    // The texts of the booking cards and dialogs have nothing left to say.
    expect(lookup(locale, "bookings")).toBeUndefined();
  });

  it("keeps the three scope messages and the venue mark's words, which replace the removed keys", () => {
    for (const locale of [en, es]) {
      for (const key of [
        "overview.scope.loading",
        "overview.scope.error",
        "overview.scope.noExchanges",
        "positions.venue.link",
        "positions.venue.line.beingBooked",
      ]) {
        expect(typeof lookup(locale, key), key).toBe("string");
      }
    }
  });

  it("finds what it is meant to guard: the scan reads the sources and sees a name written in one", () => {
    // Guards against a vacuous pass: a scan that read nothing, or that missed a name, would pass above.
    const files = scannedFiles();
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((file) => file.endsWith("discrepancies.ts"))).toBe(true);
    expect(files.some((file) => file.endsWith("en.json"))).toBe(true);
    expect(namedIn('import { usePendingBookings } from "@/features/bookings/usePendingBookings";', ["usePendingBookings"])).toEqual([
      "usePendingBookings",
    ]);
    expect(namedIn('apiFetch("/reconciliation/bookings")', ["/reconciliation/bookings"])).toEqual(["/reconciliation/bookings"]);
    expect(namedIn("useConfirmedDiscrepancies", ["usePendingBookings"])).toEqual([]);
    expect(lookup({ a: { b: "c" } }, "a.b")).toBe("c");
    expect(lookup({ a: { b: "c" } }, "a.x")).toBeUndefined();
  });
});
