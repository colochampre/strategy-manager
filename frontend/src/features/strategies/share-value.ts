/**
 * The share's value model (design § C of the unit 12f addendum). STUB (12f.10.5 RED): every function
 * answers wrongly until the GREEN writes the module.
 */

/** Why a typed text is not a value: not a number, not above 0, or above 100. */
export type DraftRefusal = "not-a-number" | "not-above-zero" | "above-hundred";

/** What a typed text reads as: its canonical form when valid, the reason when not. */
export type DraftReading = { valid: true; canonical: string } | { valid: false; refusal: DraftRefusal };

export function readStored(text: string): string | null {
  return text;
}

export function parseDraft(text: string): DraftReading {
  return { valid: true, canonical: text };
}

export function roundToHandle(_canonical: string): number {
  return 0;
}

export function handlePosition(_step: number): string {
  return "0%";
}
