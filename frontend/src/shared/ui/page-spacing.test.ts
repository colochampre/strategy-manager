import { describe, expect, it } from "vitest";

/**
 * The owner's rule (L.13): every view stacks its blocks 3 apart (`gap-3`, 12 px), as Explore and My subscriptions
 * do: cards, report boxes, sections. The one wider step is the page's title to what follows it (`gap-6`), on the
 * element that holds the `h1`. A dialog has its own inner rhythm and is not a page.
 */
const sources = import.meta.glob<string>(["/src/features/**/*.tsx", "!/src/features/**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** A block's own inner rhythm (a label over its field, a cell's lines), under the step between blocks. */
const NARROW = new Set(["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5"]);
/** Dialogs: a modal's padding and rhythm are its own. */
const isDialog = (path: string) => /Dialog\.tsx$/.test(path) || path.endsWith("/CodeEntry.tsx");

function wideStacks(path: string, source: string): string[] {
  const lines = source.split(/\r?\n/);
  const found: string[] = [];
  lines.forEach((line, index) => {
    for (const match of line.matchAll(/flex-col\b[^"]*?\bgap-(\d+(?:\.5)?)\b/g)) {
      const gap = match[1] ?? "";
      if (NARROW.has(gap)) continue;
      // The page title's step: the stack holding the h1, within the two lines after it opens.
      const titled = gap === "6" && lines.slice(index + 1, index + 3).some((next) => next.includes("<h1"));
      if (!titled) found.push(`${path}:${index + 1} gap-${gap}`);
    }
  });
  return found;
}

describe("page spacing", () => {
  it("reads the panel's views", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it("stacks every view's blocks 3 apart; only a page title steps 6 to what follows (L.13)", () => {
    const wide = Object.entries(sources)
      .filter(([path]) => !isDialog(path))
      .flatMap(([path, source]) => wideStacks(path, source));

    expect(wide).toEqual([]);
  });
});
