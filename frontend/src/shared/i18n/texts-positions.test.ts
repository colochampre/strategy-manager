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
  ["positions.venue.link", "See the discrepancy", "Ver la discrepancia"],
  [
    "positions.venue.linkName",
    "See the discrepancy, {{pair}}",
    "Ver la discrepancia, {{pair}}",
  ],
  // op.3: the order line, the venue line, the table, its reasons and its notes (section I).
  ["positions.order.open", "opening", "apertura"],
  ["positions.order.close", "closing", "cierre"],
  ["positions.order.sent", "sent {{time}} UTC", "enviada {{time}} UTC"],
  ["positions.venue.groupName", "Venue disagrees, {{pair}}", "El exchange no coincide, {{pair}}"],
  ["positions.venue.line.disagrees", "venue disagrees", "el exchange no coincide"],
  [
    "positions.venue.line.nets",
    "exchange {{venue}}, ledger {{ledger}}",
    "exchange {{venue}}, libro mayor {{ledger}}",
  ],
  ["positions.venue.line.compared", "last compared {{time}} UTC", "última comparación {{time}} UTC"],
  [
    "positions.venue.line.shared",
    "shared by {{positions}} positions on this pair",
    "compartida por {{positions}} posiciones en este par",
  ],
  ["positions.table.title", "Open positions", "Posiciones abiertas"],
  ["positions.table.empty", "No open position.", "Sin posiciones abiertas."],
  ["positions.table.margin", "Margin granted {{currency}}", "Margen otorgado {{currency}}"],
  ["positions.table.leverage", "Leverage", "Apalancamiento"],
  ["positions.table.leverageValue", "{{value}}x", "{{value}}x"],
  ["positions.table.notRecorded", "not recorded", "no registrado"],
  ["positions.table.ofOpened", "of {{opened}} opened", "de {{opened}} abiertas"],
  ["positions.table.averageOf", "average of {{fills}} fills", "promedio de {{fills}} ejecuciones"],
  [
    "positions.table.unmatched_one",
    "{{count}} open position or order could not be matched to a strategy. The Strategies page names it.",
    "{{count}} posición u orden abierta no se pudo asociar a una estrategia. La página Estrategias la nombra.",
  ],
  [
    "positions.table.unmatched_other",
    "{{count}} open positions or orders could not be matched to a strategy. The Strategies page names them.",
    "{{count}} posiciones u órdenes abiertas no se pudieron asociar a una estrategia. La página Estrategias las nombra.",
  ],
  [
    "positions.reason.UNRESOLVED_SYMBOL",
    "The pair's base currency cannot be told from the pool's currency, so the side and the size are not derived.",
    "La moneda base del par no se puede determinar a partir de la moneda del pool, por lo que el lado y el tamaño no se calculan.",
  ],
  [
    "positions.reason.SEVERAL_MARKETS",
    "The fills of this position name more than one pair.",
    "Las ejecuciones de esta posición nombran más de un par.",
  ],
  [
    "positions.reason.FLIPPED",
    "The fills sold more than was bought, or bought more than was sold. The entry price is not derived.",
    "Las ejecuciones vendieron más de lo comprado, o compraron más de lo vendido. El precio de entrada no se calcula.",
  ],
  [
    "positions.reason.other",
    "The figures could not be derived from the fills.",
    "Las cifras no se pudieron calcular a partir de las ejecuciones.",
  ],
  [
    "positions.note.margin",
    "Margin granted is what the share took from the pool when the position opened. It is not what the exchange holds now.",
    "El margen otorgado es lo que la participación tomó del pool al abrir la posición. No es lo que el exchange retiene ahora.",
  ],
  [
    "positions.note.rehearsal",
    "A dry-run position was filled by the simulated exchange, at 1x. It is not at the exchange and enters no total.",
    "Una posición de simulación fue ejecutada por el exchange simulado, a 1x. No está en el exchange real y no entra en ningún total.",
  ],
  [
    "positions.note.mixed",
    "This position holds dry-run and live fills. Neither mode can close it safely: check it against the exchange by hand.",
    "Esta posición tiene ejecuciones de simulación y en vivo. Ningún modo puede cerrarla con seguridad: verifíquela a mano contra el exchange.",
  ],
  [
    "positions.note.reservation",
    "Its reservation reads {{status}}, not FILLED.",
    "Su reserva figura como {{status}}, no FILLED.",
  ],
  // op.4: the Overview's own (section I). `openWithRehearsal` has plural forms on the total: one position that is dry run reads "1 open, dry run".
  ["overview.open.strategy", "Strategy", "Estrategia"],
  ["overview.monthlySummary.openAll_one", "{{count}} open", "{{count}} abierta"],
  ["overview.monthlySummary.openAll_other", "{{count}} open", "{{count}} abiertas"],
  ["overview.monthlySummary.openWithRehearsal_one", "{{count}} open, dry run", "{{count}} abierta, en simulación"],
  [
    "overview.monthlySummary.openWithRehearsal_other",
    "{{count}} open, {{rehearsal}} of them dry run",
    "{{count}} abiertas, {{rehearsal}} de ellas en simulación",
  ],
];

/** The detail page still writes today's live-only count, so these two are NOT removed (section I, § O Q6). */
const KEPT = [
  ["overview.monthlySummary.open_one", "{{count}} open trade not in the curve", "{{count}} operación abierta fuera de la curva"],
  ["overview.monthlySummary.open_other", "{{count}} open trades not in the curve", "{{count}} operaciones abiertas fuera de la curva"],
] as const;

/**
 * The closed trades table's words the open-positions section REUSES (design addendum section H): they must
 * exist and must not change, because the section and the table under it have to write one page in one voice.
 */
const REUSED: ReadonlyArray<readonly [string, string, string]> = [
  ["strategies.performance.trades.opened", "Opened (UTC)", "Apertura (UTC)"],
  ["strategies.performance.trades.pair", "Pair", "Par"],
  ["strategies.performance.trades.side", "Side", "Sentido"],
  ["strategies.performance.trades.size", "Size", "Tamaño"],
  ["strategies.performance.trades.entry", "Entry", "Entrada"],
  ["strategies.performance.trades.fees", "Fees {{currency}}", "Comisiones {{currency}}"],
  ["strategies.performance.trades.direction.LONG", "LONG", "LONG"],
  ["strategies.performance.trades.direction.SHORT", "SHORT", "SHORT"],
  ["strategies.performance.trades.otherFee", "+ {{amount}} {{currency}}", "+ {{amount}} {{currency}}"],
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

  it.each(REUSED)("%s, which the section reuses, is present and unchanged in both files", (key, english, spanish) => {
    expect(lookup(en, key)).toBe(english);
    expect(lookup(es, key)).toBe(spanish);
  });

  it.each(KEPT)("%s, which the detail page still writes, is kept as it was in both files", (key, english, spanish) => {
    expect(lookup(en, key)).toBe(english);
    expect(lookup(es, key)).toBe(spanish);
  });

  it("names `count` in every plural form of the Overview's count, and keeps `rehearsal` in the plural dry-run one", () => {
    for (const locale of [en, es]) {
      expect(lookup(locale, "overview.monthlySummary.openWithRehearsal")).toBeUndefined();
      expect(lookup(locale, "overview.monthlySummary.openWithRehearsal_other")).toEqual(
        expect.stringContaining("{{rehearsal}}"),
      );
      for (const key of [
        "overview.monthlySummary.openAll_one",
        "overview.monthlySummary.openAll_other",
        "overview.monthlySummary.openWithRehearsal_one",
        "overview.monthlySummary.openWithRehearsal_other",
      ]) {
        expect(lookup(locale, key), key).toEqual(expect.stringContaining("{{count}}"));
      }
    }
  });

  it("writes the unmatched sentence in the singular for one and the plural for more, in agreement, in Spanish", () => {
    const one = lookup(es, "positions.table.unmatched_one");
    const other = lookup(es, "positions.table.unmatched_other");
    expect(one).toContain("posición u orden abierta no se pudo asociar");
    expect(one).toContain("la nombra");
    expect(other).toContain("posiciones u órdenes abiertas no se pudieron asociar");
    expect(other).toContain("las nombra");
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
