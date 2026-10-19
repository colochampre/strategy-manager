import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Every leaf key of a locale, as a dotted path. */
function keysOf(value: unknown, path = ""): string[] {
  if (typeof value !== "object" || value === null) return [path];
  return Object.entries(value).flatMap(([key, child]) => keysOf(child, path === "" ? key : `${path}.${key}`));
}

/** Every non-test `.ts` and `.tsx` file under `src`, at any depth. */
function sources(directory: string = SRC): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const ENGLISH = new Set(keysOf(en));
const SPANISH = new Set(keysOf(es));

/** A key exists when it is a leaf, or when its plural forms are (`_one` and `_other`). */
function exists(locale: ReadonlySet<string>, key: string): boolean {
  return locale.has(key) || (locale.has(`${key}_one`) && locale.has(`${key}_other`));
}

/**
 * Task X.5 (owner decision 79): the cross-feature sweep. Each unit's own test checks its texts; this one holds the
 * two files together, whatever unit adds a key next.
 */
describe("the two locale files", () => {
  it("hold the same keys, over the whole files", () => {
    const onlyEnglish = [...ENGLISH].filter((key) => !SPANISH.has(key)).sort();
    const onlySpanish = [...SPANISH].filter((key) => !ENGLISH.has(key)).sort();

    // A walk that found nothing would pass for ever.
    expect(ENGLISH.size).toBeGreaterThan(400);
    expect({ onlyEnglish, onlySpanish }).toEqual({ onlyEnglish: [], onlySpanish: [] });
  });

  it("hold every key the sources name to t(), in both files", () => {
    const referenced = new Set<string>();
    const prefixes = new Set<string>();
    for (const file of sources()) {
      const code = readFileSync(file, "utf8");
      for (const match of code.matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"/g)) referenced.add(match[1] as string);
      // A key built from a name, as `strategies.new.fillModes.${mode}`: the prefix has to be a branch of both files.
      for (const match of code.matchAll(/\bt\(\s*`([A-Za-z0-9_.]+)\.\$\{/g)) prefixes.add(match[1] as string);
    }

    // The scan has to find the texts it is about: a regex that matched nothing would pass for ever.
    expect(referenced.size).toBeGreaterThan(300);
    expect(referenced.has("strategies.detail.name.rename")).toBe(true);
    expect(referenced.has("settings.delete.confirmTitle")).toBe(true);
    expect(prefixes.has("strategies.new.fillModes")).toBe(true);

    const missing: string[] = [];
    for (const key of referenced) {
      if (!exists(ENGLISH, key)) missing.push(`en ${key}`);
      if (!exists(SPANISH, key)) missing.push(`es ${key}`);
    }
    for (const prefix of prefixes) {
      if (![...ENGLISH].some((key) => key.startsWith(`${prefix}.`))) missing.push(`en ${prefix}.*`);
      if (![...SPANISH].some((key) => key.startsWith(`${prefix}.`))) missing.push(`es ${prefix}.*`);
    }
    expect(missing.sort()).toEqual([]);
  });
});
