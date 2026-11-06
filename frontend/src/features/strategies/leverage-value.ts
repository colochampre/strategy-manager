/**
 * The leverage's value model. A subscription's leverage is a whole number from 1 to 20 (the API refuses
 * anything else with a 422), so unlike the share it is a plain number: the field's text is read once and
 * the handle sits exactly on it.
 */

/** Why a typed text is not a leverage: not a whole number, or a whole number outside 1 to 20. */
export type LeverageRefusal = "not-a-whole-number" | "out-of-range";

/** What a typed text reads as: its number when valid, the reason when not. */
export type LeverageReading = { valid: true; value: number } | { valid: false; refusal: LeverageRefusal };

export const FIRST_LEVERAGE = 1;
export const LAST_LEVERAGE = 20;

const POSITION_DECIMALS = 4;
const WHOLE_NUMBER = /^\d+$/;

/**
 * What the field's text reads as. Surrounding spaces are ignored; what is left must be digits only, so a
 * sign, a decimal point, an exponent or the "x" of the display never reads as a value. A leading zero is
 * harmless ("05" is 5). The range is checked on the digits' length first, so a long run of digits is
 * refused as out of range and never rounded by a float.
 */
export function parseLeverage(text: string): LeverageReading {
  const trimmed = text.trim();
  if (!WHOLE_NUMBER.test(trimmed)) return { valid: false, refusal: "not-a-whole-number" };
  const digits = trimmed.replace(/^0+(?=\d)/, "");
  if (digits.length > String(LAST_LEVERAGE).length) return { valid: false, refusal: "out-of-range" };
  const value = Number(digits);
  if (value < FIRST_LEVERAGE || value > LAST_LEVERAGE) return { valid: false, refusal: "out-of-range" };
  return { valid: true, value };
}

/** Where the handle sits along the track, as a CSS length: `(step - 1) / 19` of it, to four decimals. */
export function leveragePosition(step: number): string {
  const percent = ((step - FIRST_LEVERAGE) / (LAST_LEVERAGE - FIRST_LEVERAGE)) * 100;
  return `${Number(percent.toFixed(POSITION_DECIMALS))}%`;
}
