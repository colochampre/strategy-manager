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
 * The help texts subscriber-safety SS.11 brought up to date: key, English, Spanish. Disabling is refused while
 * anyone holds a position (SS.8a) and the sweep closes what is left on a stopped strategy (SS.8b); a held
 * position keeps its exchange stop and can be closed by hand (SS.9); every live opening carries a stop that caps
 * the leverage (SS.3 to SS.7).
 */
const TEXTS: ReadonlyArray<readonly [string, string, string]> = [
  [
    "strategies.enableDialog.disableBody",
    "{{name}} opens nothing more, for you or for anyone trading it. It cannot be disabled while anyone holds a position on it, and a position found on it afterwards is closed at market.",
    "{{name}} no abre nada más, ni para usted ni para nadie que la opere. No se puede deshabilitar mientras alguien tenga una posición en ella, y una posición que se encuentre en ella después se cierra a mercado.",
  ],
  [
    "strategies.leave.confirmBody",
    "{{name}} will open nothing more for you. A position you hold stays open, protected by its exchange stop, and closes with the strategy's next close, and your subscription ends then. You can also close it yourself with Close now.",
    "{{name}} ya no abrirá nada más para usted. Una posición que tenga abierta sigue abierta, protegida por su stop en el exchange, y se cierra con el próximo cierre de la estrategia, y entonces termina su suscripción. También puede cerrarla usted mismo con Cerrar ahora.",
  ],
  [
    "strategies.leverage.hint",
    "The system sets this leverage on the exchange before each opening, so it applies from the next opening. A position that is already open keeps the leverage it was opened with. The higher it is, the more the same margin moves, in gains and in losses. Every live opening also carries a stop at the exchange, at the strategy's stop level, and that stop caps the leverage you may choose so that it comes before liquidation.",
    "El sistema fija este apalancamiento en el exchange antes de cada apertura, así que se aplica desde la próxima apertura. Una posición que ya está abierta conserva el apalancamiento con el que se abrió. Cuanto mayor es, más mueve el mismo margen, tanto en ganancias como en pérdidas. Cada apertura en vivo lleva además un stop en el exchange, al nivel de stop de la estrategia, y ese stop limita el apalancamiento que puede elegir para que llegue antes que la liquidación.",
  ],
  [
    "strategies.stopLevel.hint",
    "The distance from the entry price, as a percentage of price, at which a position of this strategy is stopped. The system places that stop at the exchange with every live opening; a simulated opening has none. It also limits the leverage anyone may use on it, so that the stop comes before liquidation: a stop of 10% allows up to x9, and one of 5% up to x16. A change applies to openings made after it; a position already open keeps its stop. A seat left above the new limit stops opening until its user lowers its leverage.",
    "La distancia al precio de entrada, como porcentaje del precio, a la que se detiene una posición de esta estrategia. El sistema coloca ese stop en el exchange con cada apertura en vivo; una apertura simulada no lo lleva. También limita el apalancamiento que cualquiera puede usar en ella, para que el stop llegue antes que la liquidación: un stop del 10% permite hasta x9, y uno del 5% hasta x16. Un cambio se aplica a las aperturas que se hagan después; una posición ya abierta conserva su stop. Un puesto que quede por encima del nuevo límite deja de abrir hasta que su usuario reduzca su apalancamiento.",
  ],
  [
    "strategies.description.hint",
    "Optional. Anyone who opens this strategy sees it on its public page and before subscribing, as plain text. A good place to say which leverage you recommend, within the limit your stop allows. Up to 2,000 characters.",
    "Opcional. Quien abra esta estrategia la verá en su página pública y antes de suscribirse, como texto sin formato. Es un buen lugar para indicar qué apalancamiento recomienda, dentro del límite que permite su stop. Hasta 2.000 caracteres.",
  ],
];

describe("the safety help texts", () => {
  it.each(TEXTS)("%s reads as written, in English and in Spanish", (key, english, spanish) => {
    expect(lookup(en, key)).toBe(english);
    expect(lookup(es, key)).toBe(spanish);
  });
});
