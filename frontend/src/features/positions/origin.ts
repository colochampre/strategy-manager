/**
 * The ONE table from an origin to its text key, its text class and its border class (design § H, "The marks").
 * The chip, the line and the tag all read it, and it is the only file under `features/positions` that writes
 * the amber `decision` utilities, which `panel-tokens.test.ts` allows here for decision 65: the origin
 * "Dry run" of an open position, in the words and the amber of the mode badge. Cyan (`gain`) is the origin
 * "Live", the colour of the "Live" badge; red (`loss`) is a position holding fills of both origins, because
 * neither mode can close it; an unknown origin claims nothing and has a neutral border.
 */
export type Origin = "rehearsal" | "live" | "mixed" | "unknown";

export interface OriginStyle {
  /** The i18n key of the origin's word. */
  textKey: string;
  /** The class of the word. */
  text: string;
  /** The class of a mark's border. */
  border: string;
}

export const ORIGIN_STYLE: Readonly<Record<Origin, OriginStyle>> = {
  rehearsal: { textKey: "positions.origin.rehearsal", text: "text-decision", border: "border-decision" },
  live: { textKey: "positions.origin.live", text: "text-gain", border: "border-gain" },
  mixed: { textKey: "positions.origin.mixed", text: "text-loss", border: "border-loss" },
  unknown: { textKey: "positions.origin.unknown", text: "text-ink-3", border: "border-rule-strong" },
};
