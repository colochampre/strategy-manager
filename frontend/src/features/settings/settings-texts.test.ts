import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "..");

/** Every string under a key of a locale, with its dotted path. */
function flatten(value: unknown, path = ""): [string, string][] {
  if (typeof value === "string") return [[path, value]];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) => flatten(child, path === "" ? key : `${path}.${key}`));
}

/** The non-test sources of the three places that draw Settings. */
function sources(): string[] {
  const own = (directory: string) =>
    readdirSync(directory)
      .filter((name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name))
      .map((name) => join(directory, name));
  return [
    ...own(join(SRC, "features", "settings")),
    ...own(join(SRC, "shared", "credentials")),
    join(SRC, "shared", "api", "credentials.ts"),
  ];
}

const ENGLISH = new Map(flatten(en));
const SPANISH = new Map(flatten(es));

/** A key exists when it is a leaf, or when its plural forms are (`_one` and `_other`). */
function exists(locale: ReadonlyMap<string, string>, key: string): boolean {
  return locale.has(key) || (locale.has(`${key}_one`) && locale.has(`${key}_other`));
}

describe("every text of Settings exists in both languages (spec: every new key exists in both files)", () => {
  it("test_every_new_key_exists_in_both_files: each key the sources reference is in en.json and in es.json", () => {
    const referenced = new Set<string>();
    const prefixes = new Set<string>();
    for (const file of sources()) {
      const code = readFileSync(file, "utf8");
      expect(code.length, file).toBeGreaterThan(50);
      for (const match of code.matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"/g)) referenced.add(match[1] as string);
      // A key built from a name, as `settings.form.error.${reason}`: the prefix has to be a branch of both files.
      for (const match of code.matchAll(/\bt\(\s*`([A-Za-z0-9_.]+)\.\$\{/g)) prefixes.add(match[1] as string);
    }

    // The scan has to find the texts it is about: a regex that matched nothing would pass for ever.
    expect(referenced.size).toBeGreaterThan(40);
    expect(referenced.has("settings.delete.confirmTitle")).toBe(true);
    expect(referenced.has("settings.delete.reasons.enabledStrategies")).toBe(true);
    expect(prefixes.has("settings.form.error")).toBe(true);

    const missing: string[] = [];
    for (const key of referenced) {
      if (!exists(ENGLISH, key)) missing.push(`en ${key}`);
      if (!exists(SPANISH, key)) missing.push(`es ${key}`);
    }
    for (const prefix of prefixes) {
      if (![...ENGLISH.keys()].some((key) => key.startsWith(`${prefix}.`))) missing.push(`en ${prefix}.*`);
      if (![...SPANISH.keys()].some((key) => key.startsWith(`${prefix}.`))) missing.push(`es ${prefix}.*`);
    }
    expect(missing).toEqual([]);
  });

  it("has the same Settings keys in both files", () => {
    const englishKeys = flatten(en.settings).map(([key]) => key).sort();
    const spanishKeys = flatten(es.settings).map(([key]) => key).sort();

    expect(englishKeys.length).toBeGreaterThan(80);
    expect(spanishKeys).toEqual(englishKeys);
  });

  it("has every dynamic branch of a prefix complete in both files: one error per refusal, one mark per word", () => {
    const names = (locale: ReadonlyMap<string, string>, prefix: string) =>
      [...locale.keys()].filter((key) => key.startsWith(`${prefix}.`)).map((key) => key.slice(prefix.length + 1)).sort();

    for (const prefix of ["settings.form.error", "settings.form.confirm", "scope.mark"]) {
      expect(names(ENGLISH, prefix).length, prefix).toBeGreaterThan(1);
      expect(names(SPANISH, prefix), prefix).toEqual(names(ENGLISH, prefix));
    }
  });
});

describe("the Spanish lines of a refused delete agree with their noun (design § J)", () => {
  const line = (key: string) => SPANISH.get(`settings.delete.reasons.${key}`) as string;

  it.each([
    ["enabledStrategies", "estrategia activada", "Desactívela primero", "estrategias activadas", "Desactívelas primero"],
    ["allocations", "asignación abierta", "Termina cuando se cierra su posición", "asignaciones abiertas", "Terminan cuando se cierran sus posiciones"],
    ["liveReservations", "reserva vigente", "para una orden. Espere a que termine", "reservas vigentes", "para órdenes. Espere a que terminen"],
    ["inFlightAttempts", "orden que se está enviando", "Espere a que termine", "órdenes que se están enviando", "Espere a que terminen"],
  ])("%s: one is singular and feminine, other is plural, each in a single key", (key, oneNoun, oneVerb, otherNoun, otherVerb) => {
    const one = line(`${key}_one`);
    const other = line(`${key}_other`);

    expect(one, key).toContain(oneNoun);
    expect(one, key).toContain(oneVerb);
    expect(other, key).toContain(otherNoun);
    expect(other, key).toContain(otherVerb);
    // The two sentences of a line live in one key, and the count is in the key's own text.
    expect(one).toContain("{{count}}");
    expect(other).toContain("{{count}}");
    expect(one.split(". ").length).toBeGreaterThanOrEqual(2);
  });

  it("addresses the owner as usted in every delete text that gives an instruction", () => {
    const imperatives = [
      line("enabledStrategies_one"),
      line("enabledStrategies_other"),
      line("liveReservations_one"),
      line("inFlightAttempts_other"),
      SPANISH.get("settings.delete.errors.gone") as string,
      SPANISH.get("settings.delete.errors.unknown") as string,
    ].join(" ");

    for (const usted of ["Desactívela", "Desactívelas", "Espere", "Cierre"]) expect(imperatives).toContain(usted);
    // The familiar forms would be a different register.
    for (const tu of ["Desactívala", "Desactívalas", "Espera ", "Cierra "]) expect(imperatives).not.toContain(tu);
  });
});
