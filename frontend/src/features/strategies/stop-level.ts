/**
 * A strategy's stop level as a percentage of price, and the leverage it caps (subscriber-safety D5).
 * Mirrors the server: the level goes from 1 to 50 with at most two decimals, and a seat may not trade above
 * `min(20, floor(100 / (level + 1)))`, the one-point buffer being the maintenance margin. 10 gives 9x, 5 gives 16x.
 */

export const FIRST_STOP_LEVEL = 1;
export const LAST_STOP_LEVEL = 50;
/** What the registration form offers, and what every strategy that existed at the deploy got. */
export const DEFAULT_STOP_LEVEL = "10";

const CEILING = 20;
const MAX_DECIMALS = 2;
const NUMBER = /^\d+(\.\d+)?$/;

/** Why a typed text is not a stop level. */
export type StopLevelRefusal = "not-a-number" | "out-of-range" | "too-many-decimals";

/** What a typed text reads as: the level as the API takes it when valid, the reason when not. */
export type StopLevelReading = { valid: true; canonical: string } | { valid: false; refusal: StopLevelRefusal };

/** The text's value in hundredths of a percent, read from the digits so no float ever rounds it. */
function hundredths(text: string): number {
  const [whole = "", fraction = ""] = text.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(MAX_DECIMALS, "0"));
}

export function readStopLevel(text: string): StopLevelReading {
  const trimmed = text.trim();
  if (!NUMBER.test(trimmed)) return { valid: false, refusal: "not-a-number" };
  const [whole = "", fraction = ""] = trimmed.split(".");
  const canonicalWhole = whole.replace(/^0+(?=\d)/, "");
  // Trailing zeros past the second decimal are the same value, as the server reads them.
  const significant = fraction.replace(/0+$/, "");
  if (significant.length > MAX_DECIMALS) return { valid: false, refusal: "too-many-decimals" };
  // A long run of digits is out of range before it is ever turned into a number.
  if (canonicalWhole.length > String(LAST_STOP_LEVEL).length) return { valid: false, refusal: "out-of-range" };
  const cents = hundredths(`${canonicalWhole}.${significant}`);
  if (cents < FIRST_STOP_LEVEL * 100 || cents > LAST_STOP_LEVEL * 100) return { valid: false, refusal: "out-of-range" };
  return { valid: true, canonical: significant === "" ? canonicalWhole : `${canonicalWhole}.${significant}` };
}

/**
 * The most a seat may trade at under a stop of `stopLevel` (a level as the API writes it, "10.00", or as typed).
 * With no level to read it is the plain ceiling: the server still refuses a leverage above the cap.
 */
export function maxLeverage(stopLevel: string | undefined): number {
  if (stopLevel === undefined) return CEILING;
  const reading = readStopLevel(stopLevel);
  if (!reading.valid) return CEILING;
  return Math.min(CEILING, Math.floor(10000 / (hundredths(reading.canonical) + 100)));
}
