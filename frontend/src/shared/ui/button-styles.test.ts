import { describe, expect, it } from "vitest";

import { GAIN_OUTLINE } from "@/shared/ui/button-styles";

/**
 * The owner's rule (L26): every green button is drawn as the prototype's "Tengo un código", an outline in the gain
 * colour on no fill, never the filled green with dark text it replaced. Dots, slider thumbs and marks may still be
 * filled green; what this looks for is the filled button's pair, `bg-gain` with `text-ground`, on one line.
 */
const sources = import.meta.glob<string>(
  ["/src/**/*.tsx", "/src/**/*.ts", "!/src/**/*.test.tsx", "!/src/**/*.test.ts"],
  { query: "?raw", import: "default", eager: true },
);

const FILLED = /\bbg-gain(?![-/\w])/;

function filledGreenButtons(): string[] {
  const found: string[] = [];
  for (const [path, source] of Object.entries(sources)) {
    source.split(/\r?\n/).forEach((line, index) => {
      if (FILLED.test(line) && line.includes("text-ground")) found.push(`${path}:${index + 1}`);
    });
  }
  return found;
}

describe("green buttons", () => {
  it("are outlines in the gain colour, with no filled green left anywhere (L26)", () => {
    expect(filledGreenButtons()).toEqual([]);
  });

  it("share one outline: the gain border at 45 %, no fill, the bright gain text", () => {
    expect(GAIN_OUTLINE.split(" ")).toEqual(
      expect.arrayContaining(["border", "border-gain/45", "bg-transparent", "text-gain-bright"]),
    );
    expect(FILLED.test(GAIN_OUTLINE)).toBe(false);
  });

  it("finds a filled green button when there is one, so the first rule is not vacuous", () => {
    expect(FILLED.test('className="rounded-lg bg-gain px-3 text-ground"')).toBe(true);
    expect(FILLED.test('className="bg-gain/10"')).toBe(false);
    expect(FILLED.test('className="bg-gain-bright"')).toBe(false);
  });
});
