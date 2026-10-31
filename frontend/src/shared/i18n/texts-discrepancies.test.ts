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

/** Every dotted path to a string leaf under `prefix`, sorted. */
function leaves(locale: unknown, prefix: string): string[] {
  const out: string[] = [];
  const walk = (node: unknown, path: string) => {
    if (typeof node === "string") out.push(path);
    else if (typeof node === "object" && node !== null) {
      for (const [key, child] of Object.entries(node)) walk(child, `${path}.${key}`);
    }
  };
  walk(lookup(locale, prefix), prefix);
  return out.sort();
}

/**
 * The Discrepancies texts (design addendum "PR 15" section I and the specs' state tables, approved with the
 * prototype `Discrepancies.html` on 2026-10-16): key, English, Spanish. The English is the prototype's letter
 * for letter (examples 1 to 11 and 13). The Spanish is examples 10, 12, 13 and 15 and the note under example 10,
 * with the register changed from "tu" to "usted" (task note N1, owner decision 66): "Requiere su atencion",
 * "Pida una conciliacion manual". N4: the English of ATTRIBUTABLE_SINGLE_ALLOCATION is the prototype author's.
 */
const TEXTS: ReadonlyArray<readonly [string, string, string]> = [
  ["nav.discrepancies", "Discrepancies", "Discrepancias"],
  ["discrepancies.title", "Discrepancies", "Discrepancias"],
  [
    "discrepancies.lede",
    "Where the exchange and the ledger still disagree after repeated comparisons. A close the system can attribute to one strategy is booked automatically; the rest is listed under Needs you.",
    "Donde el exchange y el libro mayor siguen sin coincidir tras comparaciones repetidas. Un cierre que el sistema puede atribuir a una estrategia se registra automáticamente; el resto aparece en Requiere su atención.",
  ],
  [
    "discrepancies.badgeName_one",
    "{{count}} discrepancy needs you",
    "{{count}} discrepancia requiere su atención",
  ],
  [
    "discrepancies.badgeName_other",
    "{{count}} discrepancies need you",
    "{{count}} discrepancias requieren su atención",
  ],
  // The three sections, and the two design section I keys that name them.
  ["discrepancies.section.needsYou", "Needs you", "Requiere su atención"],
  ["discrepancies.section.beingBooked", "Being booked", "Registrándose"],
  ["discrepancies.section.booked", "Booked automatically", "Registradas automáticamente"],
  ["discrepancies.booked", "Booked automatically", "Registradas automáticamente"],
  ["discrepancies.beingBooked", "Being booked automatically.", "Se está registrando automáticamente."],
  [
    "discrepancies.note.beingBooked",
    "Nothing here needs you. If it cannot be booked, it moves to Needs you.",
    "Nada de esto requiere su atención. Si no se puede registrar, pasa a Requiere su atención.",
  ],
  [
    "discrepancies.note.booked",
    "The last 30 days, newest first, at most 100.",
    "Los últimos 30 días, de la más reciente a la más antigua, hasta 100.",
  ],
  // The empty states: never an all-clear without having looked (design section H, K rows 8 and 14).
  [
    "discrepancies.empty.needsYou",
    "Nothing needs you. The venue agrees with the ledger on every confirmed comparison.",
    "Nada requiere su atención. El exchange coincide con el libro mayor en cada comparación confirmada.",
  ],
  ["discrepancies.empty.needsYouWhileBooking", "Nothing needs you.", "Nada requiere su atención."],
  ["discrepancies.empty.booked", "No booking in the last 30 days.", "Ningún registro en los últimos 30 días."],
  // The read line and the read states.
  ["discrepancies.read.loading", "Reading discrepancies…", "Leyendo discrepancias…"],
  [
    "discrepancies.read.failed",
    "Discrepancies could not be read, so this page cannot say whether anything needs you.",
    "No se pudieron leer las discrepancias, así que esta página no puede decir si algo requiere su atención.",
  ],
  ["discrepancies.read.lastRead", "Last read", "Última lectura"],
  ["discrepancies.read.time", "{{time}} UTC", "{{time}} UTC"],
  ["discrepancies.read.refresh", "Read again", "Leer de nuevo"],
  [
    "discrepancies.read.stale",
    "Could not be refreshed since {{time}} UTC.",
    "No se pudo actualizar desde las {{time}} UTC.",
  ],
  [
    "discrepancies.read.dryRun",
    "Nothing is compared with the venue for you: you are in simulation with nothing real, or the brake is on.",
    "No se compara nada con el exchange para usted: está en simulación sin nada real, o el freno está activo.",
  ],
  // The kind in words (the four verdicts of the classification ladder) and the two reasons that replace it.
  [
    "discrepancies.kind.NO_MATCHING_ALLOCATION",
    "The venue holds a position no strategy opened.",
    "El exchange tiene una posición que ninguna estrategia abrió.",
  ],
  [
    "discrepancies.kind.AMBIGUOUS_PARTIAL_REDUCE",
    "The venue reduced a position several strategies share; which one cannot be told.",
    "El exchange redujo una posición que comparten varias estrategias; no se puede saber cuál.",
  ],
  [
    "discrepancies.kind.ATTRIBUTABLE_FULL_CLOSE",
    "The venue closed a position the ledger holds open.",
    "El exchange cerró una posición que el libro mayor tiene abierta.",
  ],
  [
    "discrepancies.kind.ATTRIBUTABLE_SINGLE_ALLOCATION",
    "The venue reduced a position only one strategy holds.",
    "El exchange redujo una posición que solo tiene una estrategia.",
  ],
  [
    "discrepancies.reason.SEVERAL_ALLOCATIONS",
    "The venue closed a position several strategies share; one booking cannot split it.",
    "El exchange cerró una posición que comparten varias estrategias; un solo registro no puede repartirla.",
  ],
  ["discrepancies.reason.NOT_BOOKED", "Could not be booked automatically.", "No se pudo registrar automáticamente."],
  // One item: its labels and what the owner can do.
  ["discrepancies.label.exchange", "Exchange", "Exchange"],
  ["discrepancies.label.ledger", "Ledger", "Libro mayor"],
  ["discrepancies.label.difference", "Difference", "Diferencia"],
  ["discrepancies.label.strategy", "Strategy", "Estrategia"],
  ["discrepancies.label.strategies", "Strategies", "Estrategias"],
  ["discrepancies.label.noStrategy", "No strategy", "Ninguna estrategia"],
  // K row 13: an allocation whose strategy row is missing. Not in the prototype; the wording is the spec's.
  ["discrepancies.label.unknownStrategy", "unknown strategy", "estrategia desconocida"],
  ["discrepancies.label.confirmed", "Confirmed", "Confirmada"],
  ["discrepancies.label.lastCompared", "Last compared", "Última comparación"],
  ["discrepancies.label.whatYouCanDo", "What you can do", "Qué puede hacer"],
  [
    "discrepancies.action.manual",
    "Ask for a manual reconciliation. Nothing in this panel can book it.",
    "Pida una conciliación manual. Nada en este panel puede registrarla.",
  ],
  [
    "discrepancies.action.byHand",
    "Close it on the exchange by hand. The next comparison resolves it.",
    "Ciérrela a mano en el exchange. La próxima comparación la resuelve.",
  ],
  // The booked list: its eight headings and the values of "By" and "Now".
  ["discrepancies.table.booked", "Booked (UTC)", "Registrada (UTC)"],
  ["discrepancies.table.pair", "Pair", "Par"],
  ["discrepancies.table.side", "Side", "Sentido"],
  ["discrepancies.table.quantity", "Quantity", "Cantidad"],
  ["discrepancies.table.strategy", "Strategy", "Estrategia"],
  ["discrepancies.table.fills", "Fills", "Ejecuciones"],
  ["discrepancies.table.by", "By", "Por"],
  ["discrepancies.table.now", "Now", "Ahora"],
  ["discrepancies.by.automatic", "automatically", "automáticamente"],
  ["discrepancies.by.owner", "by hand", "a mano"],
  [
    "discrepancies.now.waiting",
    "waiting for the next comparison",
    "a la espera de la próxima comparación",
  ],
  ["discrepancies.now.agrees", "the venue agrees again", "el exchange vuelve a coincidir"],
  // The venue mark of an open position (examples 14 to 16): the words of its state, copied from the prototype.
  [
    "positions.venue.line.beingBooked",
    "being booked automatically",
    "se está registrando automáticamente",
  ],
  [
    "positions.venue.line.reason.NOT_BOOKED",
    "could not be booked automatically",
    "no se pudo registrar automáticamente",
  ],
  [
    "positions.venue.line.reason.SEVERAL_ALLOCATIONS",
    "one booking cannot split it",
    "un solo registro no puede repartirla",
  ],
  [
    "positions.venue.line.reason.AMBIGUOUS_PARTIAL_REDUCE",
    "which strategy it reduced cannot be told",
    "no se puede saber a qué estrategia redujo",
  ],
  // The Overview's three scope messages, reworded: they no longer speak of pending bookings (example 13).
  ["overview.scope.loading", "Loading exchanges…", "Cargando exchanges…"],
  [
    "overview.scope.error",
    "The pools are hidden because the exchanges could not be loaded, so they cannot be filtered.",
    "Los pools están ocultos porque no se pudieron cargar los exchanges y no se pueden filtrar.",
  ],
  [
    "overview.scope.noExchanges",
    "No exchange is configured, so there are no pools to show.",
    "No hay ningún exchange configurado, por lo que no hay pools que mostrar.",
  ],
];

/** Words of the "tu" register: the panel's Spanish addresses the owner as "usted" (note N1). */
const TU_REGISTER = /\b(tu|tus|ti|puedes|pide|pides|ciérrala|ciérralo|tienes|quieres)\b/i;

describe("the Discrepancies texts exist in both languages as approved", () => {
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

  it("writes the badge's name in two plural forms that name `count`, and in no bare form", () => {
    for (const locale of [en, es]) {
      expect(lookup(locale, "discrepancies.badgeName")).toBeUndefined();
      expect(lookup(locale, "discrepancies.badgeName_one"), "one").toEqual(expect.stringContaining("{{count}}"));
      expect(lookup(locale, "discrepancies.badgeName_other"), "other").toEqual(expect.stringContaining("{{count}}"));
    }
  });

  it("has no key under discrepancies.* in one language that the other lacks", () => {
    expect(leaves(es, "discrepancies")).toEqual(leaves(en, "discrepancies"));
  });

  it("addresses the owner as usted in every Spanish text of the page, never as tu", () => {
    const tu = leaves(es, "discrepancies")
      .map((path) => [path, lookup(es, path)] as const)
      .filter(([, text]) => typeof text === "string" && TU_REGISTER.test(text))
      .map(([path]) => path);
    expect(tu).toEqual([]);
  });
});
