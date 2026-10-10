import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    const isSource = /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name);
    return isSource ? [path] : [];
  });
}

/**
 * Every region of a file that feeds a class list: a `className=` attribute
 * (string literal or expression container) and a `cn(...)` call.
 */
function classRegions(text: string): string[] {
  const regions: string[] = [];
  for (const match of text.matchAll(/className=(?:"[^"]*"|\{[^}]*\})/g)) regions.push(match[0]);
  for (const match of text.matchAll(/\bcn\([^)]*\)/g)) regions.push(match[0]);
  return regions;
}

const HEX = /#[0-9a-fA-F]{3,8}\b/;
const VAR = /var\(/;
const UTILITY = "(?:bg|text|border|ring|outline|fill|stroke|divide|from|to|via|placeholder|caret|accent|shadow|decoration)";
const REMOVED_TOKEN = new RegExp(
  `\\b${UTILITY}-(?:surface-(?:700|800|850|900|950)|edge|ink-(?:100|300|500)|accent|profit|idle)\\b`,
);

describe("theme rules", () => {
  const files = sourceFiles(SRC);

  it("test_no_hex_colour_or_var_inside_classname_across_renamed_components", () => {
    expect(files.length).toBeGreaterThan(5);
    const offenders: string[] = [];
    for (const file of files) {
      for (const region of classRegions(readFileSync(file, "utf8"))) {
        if (HEX.test(region) || VAR.test(region)) {
          offenders.push(`${relative(SRC, file)}: ${region}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("finds the class regions it is meant to guard", () => {
    // Guards against a vacuous pass: the scanner must see real class lists.
    const total = files.reduce((n, f) => n + classRegions(readFileSync(f, "utf8")).length, 0);
    expect(total).toBeGreaterThan(20);
    expect(classRegions('<a className="bg-[#fff]" />')).toHaveLength(1);
    expect(HEX.test("bg-[#1FA6B8]")).toBe(true);
    expect(VAR.test("bg-[var(--x)]")).toBe(true);
  });

  it("test_removed_tokens_are_not_used_by_any_source_file", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const hit = REMOVED_TOKEN.exec(readFileSync(file, "utf8"));
      if (hit) offenders.push(`${relative(SRC, file)}: ${hit[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  it("test_index_css_holds_direction_a_tokens_and_no_removed_ones", () => {
    const css = readFileSync(join(SRC, "index.css"), "utf8");
    for (const removed of [
      "--color-surface-",
      "--color-edge",
      "--color-ink-100",
      "--color-ink-300",
      "--color-ink-500",
      "--color-accent",
      "--color-profit",
      "--color-idle",
      "JetBrains Mono",
    ]) {
      expect(css).not.toContain(removed);
    }
    for (const added of [
      "--color-ground: #0C1116",
      "--color-panel: #141B22",
      "--color-panel-2: #1B242C",
      "--color-rule: #28333C",
      "--color-rule-soft: #1E272F",
      "--color-rule-strong: #3D4E5C",
      "--color-ink: #E7EDF1",
      "--color-ink-2: #A9B8C3",
      "--color-ink-3: #7A8C99",
      "--color-gain: #1FA6B8",
      "--color-gain-bright: #6FD0DC",
      "--color-loss: #E0644B",
      "--color-decision: #CE8018",
      "--color-gain-6:",
      "--color-loss-6:",
      "--font-display:",
      "--font-sans:",
      "--font-mono:",
    ]) {
      expect(css).toContain(added);
    }
  });

  it("test_no_non_test_source_file_has_a_style_prop", () => {
    // The CSP the panel is served with sends no `style-src 'unsafe-inline'`, so a style attribute or a style
    // property is dropped silently in production only. The spec forbids both, not only the JSX prop.
    const STYLE_USE = /\bstyle\s*=|\.style\b|\bsetProperty\b|\bcssText\b|setAttribute\(\s*["']style["']/;
    // Guards against a vacuous pass: the pattern must see every spelling it is meant to forbid.
    for (const spelling of [
      '<div style={{ width: 1 }} />',
      'node.style.width = "1px"',
      'node.style.setProperty("--x", "1")',
      'node.style.cssText = "width: 1px"',
      'node.setAttribute("style", "width: 1px")',
      "node.setAttribute('style', 'width: 1px')",
    ]) {
      expect(STYLE_USE.test(spelling)).toBe(true);
    }
    expect(STYLE_USE.test('<div className="w-1" />')).toBe(false);

    expect(files.length).toBeGreaterThan(5);
    const offenders = files.filter((file) => STYLE_USE.test(readFileSync(file, "utf8"))).map((file) => relative(SRC, file));
    expect(offenders).toEqual([]);
  });

  it("test_hex_colours_live_only_in_index_css", () => {
    const offenders = files.filter((f) => HEX.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => relative(SRC, f))).toEqual([]);
  });
});
