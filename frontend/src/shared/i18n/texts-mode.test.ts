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

const TEXTS: [key: string, english: string, spanish: string][] = [
  ["status.simulation", "Simulation", "Simulación"],
  ["status.forced", "Simulation forced", "Simulación forzada"],
  ["status.live", "Live", "En vivo"],
  [
    "mode.forcedHint",
    "The brake is on: everyone is in simulation until it is released.",
    "El freno está activo: todos operan en simulación hasta que se libere.",
  ],
  ["mode.change", "Mode: {{mode}}. Change it", "Modo: {{mode}}. Cambiarlo"],
  ["mode.toLive.title", "Go live?", "¿Operar en vivo?"],
  [
    "mode.toLive.body",
    "Real orders will be placed on your exchanges with your capital, from the next opening signal on.",
    "Se colocarán órdenes reales en sus exchanges con su capital, a partir de la próxima señal de apertura.",
  ],
  [
    "mode.toLive.note",
    "Simulated positions you hold stay simulated, and close in simulation.",
    "Las posiciones simuladas que tenga siguen simuladas y se cierran en simulación.",
  ],
  ["mode.toLive.confirm", "Go live", "Operar en vivo"],
  ["mode.toSimulation.title", "Move to simulation?", "¿Pasar a simulación?"],
  [
    "mode.toSimulation.body",
    "Openings will be simulated against your real balance. No real order is placed for them.",
    "Las aperturas se simularán sobre su saldo real. No se coloca ninguna orden real por ellas.",
  ],
  ["mode.toSimulation.note", "This needs nothing real held.", "Para esto no debe tener nada real abierto."],
  ["mode.toSimulation.confirm", "Move to simulation", "Pasar a simulación"],
  ["mode.cancel", "Cancel", "Cancelar"],
  ["mode.pending", "Changing…", "Cambiando…"],
  [
    "mode.errors.brakeOn",
    "The brake is on: everyone is in simulation until it is released, so the mode cannot change.",
    "El freno está activo: todos operan en simulación hasta que se libere, así que el modo no puede cambiar.",
  ],
  [
    "mode.errors.needsKey",
    "Going live needs an active key that can trade. Add one in Settings.",
    "Para operar en vivo necesita una clave activa que pueda operar. Agregue una en Configuración.",
  ],
  [
    "mode.errors.notFlat",
    "Going to simulation needs nothing real held. Still open:",
    "Para pasar a simulación no debe tener nada real abierto. Siguen abiertas:",
  ],
  [
    "mode.errors.unknown",
    "The mode could not be changed. Try again.",
    "No se pudo cambiar el modo. Inténtelo de nuevo.",
  ],
];

describe("the mode's texts exist in both languages", () => {
  it.each(TEXTS)("%s", (key, english, spanish) => {
    expect(lookup(en, key)).toBe(english);
    expect(lookup(es, key)).toBe(spanish);
  });

  it("no longer has one dry-run label for the whole server", () => {
    expect(lookup(en, "status.dryRun")).toBeUndefined();
    expect(lookup(es, "status.dryRun")).toBeUndefined();
  });
});
