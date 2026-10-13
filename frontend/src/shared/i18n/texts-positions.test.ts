import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/** The leaf at a dotted path, or undefined. */
function lookup(locale: unknown, path: string): unknown {
  let node: unknown = locale;
  for (const part of path.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

/**
 * The open-positions texts this unit draws (design addendum section I, approved with the prototype on
 * 2026-10-12): key, English, Spanish. The list GROWS with the units: op.3 adds the table's, the notes' and the
 * lines' keys, and op.4 closes it with the Overview's three. The English is the prototype's letter for letter;
 * the Spanish is example 25's, and section I's where the prototype draws none.
 */
const TEXTS: ReadonlyArray<readonly [string, string, string]> = [
  ["positions.state.figures.open", "Open", "Abiertas"],
  ["positions.state.figures.orders", "Orders in flight", "Órdenes en curso"],
  ["positions.state.figures.lastRead", "Last read", "Última lectura"],
  ["positions.state.figures.time", "{{time}} UTC", "{{time}} UTC"],
  ["positions.state.notShown", "Not on this list: {{items}}.", "Fuera de esta lista: {{items}}."],
  ["positions.state.archived", "archived", "archivada"],
  ["positions.state.unreadable", "figures not readable", "cifras no legibles"],
  ["positions.state.refresh", "Read again", "Leer de nuevo"],
  ["positions.state.loading", "Reading open positions…", "Leyendo posiciones abiertas…"],
  [
    "positions.state.error",
    "Open positions could not be read. A row without a mark does not mean that nothing is open.",
    "No se pudieron leer las posiciones abiertas. Una fila sin marca no significa que no haya nada abierto.",
  ],
  [
    "positions.state.stale",
    "Could not be refreshed since {{time}} UTC.",
    "No se pudo actualizar desde las {{time}} UTC.",
  ],
  ["positions.marks.name", "Open positions of {{name}}", "Posiciones abiertas de {{name}}"],
  ["positions.origin.rehearsal", "Dry run", "Simulación"],
  ["positions.origin.live", "Live", "En vivo"],
  ["positions.origin.mixed", "Dry run and live", "Simulación y en vivo"],
  ["positions.origin.unknown", "origin unknown", "origen desconocido"],
  ["positions.sideUnreadable", "side not readable", "lado no legible"],
  ["positions.order.inFlight", "order in flight", "orden en curso"],
  ["positions.venue.disagrees", "Venue disagrees", "El exchange no coincide"],
  [
    "positions.venue.noProposal",
    "No booking is proposed for it.",
    "No hay un registro propuesto para esta diferencia.",
  ],
  ["positions.venue.link", "See the pending decision", "Ver la decisión pendiente"],
  [
    "positions.venue.linkName",
    "See the pending decision, {{pair}}",
    "Ver la decisión pendiente, {{pair}}",
  ],
];

/** Keys of the first writing of the design that never existed in a locale file and must not (section I). */
const NO_LONGER_EXIST = [
  "positions.state.none",
  "positions.state.some",
  "positions.state.positions_one",
  "positions.state.positions_other",
  "positions.state.orders_one",
  "positions.state.orders_other",
  "positions.venue.detail",
  "positions.venue.shared",
];

describe("the open-positions texts of the Strategies page exist in both languages", () => {
  it.each(TEXTS)("%s is in en.json as approved", (key, english) => {
    expect(lookup(en, key)).toBe(english);
  });

  it.each(TEXTS)("%s is in es.json as approved", (key, _english, spanish) => {
    expect(lookup(es, key)).toBe(spanish);
  });

  it("holds a non-empty text for every key, in both files", () => {
    const empty: string[] = [];
    for (const [key] of TEXTS) {
      for (const [name, locale] of [["en", en], ["es", es]] as const) {
        const text = lookup(locale, key);
        if (typeof text !== "string" || text.trim() === "") empty.push(`${name} ${key}`);
      }
    }
    expect(empty).toEqual([]);
  });

  it("writes none of the keys the design dropped, in either file", () => {
    const present: string[] = [];
    for (const key of NO_LONGER_EXIST) {
      if (lookup(en, key) !== undefined) present.push(`en ${key}`);
      if (lookup(es, key) !== undefined) present.push(`es ${key}`);
    }
    expect(present).toEqual([]);
  });

  it("has no text that says nothing is open anywhere (owner decision of 2026-10-12)", () => {
    const group = (locale: unknown) => JSON.stringify(lookup(locale, "positions") ?? {}).toLowerCase();
    expect(group(en)).not.toContain("anywhere");
    expect(group(en)).not.toContain("no exchange");
  });
});
