/**
 * The share's value model (design § C of the unit 12f addendum). The share is one decimal string:
 * nothing here adds, multiplies or converts it. The only arithmetic is the handle's rounding to a whole
 * step and its position on the track, and neither touches the value that is saved.
 */

/** Why a typed text is not a value: not a number, not above 0, above 100, or of too many decimal places. */
export type DraftRefusal = "not-a-number" | "not-above-zero" | "above-hundred" | "too-many-decimals";

/** What a typed text reads as: its canonical form when valid, the reason when not. */
export type DraftReading = { valid: true; canonical: string } | { valid: false; refusal: DraftRefusal };

/** A stored share is a plain decimal with a dot: digits, then optionally a dot and digits. */
const STORED_TEXT = /^(\d+)(?:\.(\d+))?$/;
/** A typed share may use one comma for the dot; digits are needed on both sides of the separator. */
const TYPED_TEXT = /^(\d+)(?:[.,](\d+))?$/;

const FIRST_STEP = 1;
const LAST_STEP = 100;
const HALF_UP_DIGIT = "5";
const POSITION_DECIMALS = 4;
/** The API refuses a share of more than 18 decimal places (owner decision 50). */
const MAX_DECIMALS = 18;

/** Digits and fraction into the canonical form: no leading zeros, no trailing fractional zeros. */
function canonicalOf(integer: string, fraction: string): string {
  const whole = integer.replace(/^0+(?=\d)/, "");
  const decimals = fraction.replace(/0+$/, "");
  return decimals === "" ? whole : `${whole}.${decimals}`;
}

/** Whether a canonical value is above 100, compared on its digits so a long fraction is never rounded away. */
function isAboveHundred(canonical: string): boolean {
  const [integer = "", fraction = ""] = canonical.split(".");
  if (integer.length !== 3) return integer.length > 3;
  return integer > "100" || (integer === "100" && fraction !== "");
}

/** Whether a canonical value has more decimal places than the API takes, counted on its digits. */
function hasTooManyDecimals(canonical: string): boolean {
  const fraction = canonical.split(".")[1] ?? "";
  return fraction.length > MAX_DECIMALS;
}

/**
 * `strategy.allocation_percent` as the server wrote it, in canonical form, or `null` when the text is
 * not a plain decimal (an exponent, a sign, an empty string): never a guess.
 */
export function readStored(text: string): string | null {
  const match = STORED_TEXT.exec(text);
  if (match === null) return null;
  return canonicalOf(match[1] ?? "", match[2] ?? "");
}

/**
 * What the field's text reads as. Nothing is trimmed or guessed into a value: the text must be digits,
 * with at most one separator (a dot or a comma) between digits on both sides.
 */
export function parseDraft(text: string): DraftReading {
  const match = TYPED_TEXT.exec(text);
  if (match === null) return { valid: false, refusal: "not-a-number" };
  const canonical = canonicalOf(match[1] ?? "", match[2] ?? "");
  if (canonical === "0") return { valid: false, refusal: "not-above-zero" };
  if (isAboveHundred(canonical)) return { valid: false, refusal: "above-hundred" };
  if (hasTooManyDecimals(canonical)) return { valid: false, refusal: "too-many-decimals" };
  return { valid: true, canonical };
}

/**
 * The handle's whole step for a canonical value: rounded half up and clamped from 1 to 100, so the range
 * input and the drawing always receive a valid step. Done on the digits, not on a float.
 */
export function roundToHandle(canonical: string): number {
  const [integer = "0", fraction = ""] = canonical.split(".");
  const rounded = Number(integer) + ((fraction[0] ?? "0") >= HALF_UP_DIGIT ? 1 : 0);
  return Math.min(LAST_STEP, Math.max(FIRST_STEP, rounded));
}

/** Where the handle sits along the track, as a CSS length: `(step - 1) / 99` of it, to four decimals. */
export function handlePosition(step: number): string {
  const percent = ((step - FIRST_STEP) / (LAST_STEP - FIRST_STEP)) * 100;
  return `${Number(percent.toFixed(POSITION_DECIMALS))}%`;
}
