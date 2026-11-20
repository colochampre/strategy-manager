/** Where a CUIT stands as it is typed: too short to judge yet, a valid number, or one that can never be. */
export type CuitState = "typing" | "valid" | "invalid";

const WEIGHTS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];

/**
 * The check digit of a CUIT's first ten digits, or none when no digit can complete them (a remainder of 1), the same
 * rule the server applies (`identity/domain/profile.py`).
 */
function checkDigit(firstTen: string): number | null {
  const sum = WEIGHTS.reduce((total, weight, index) => total + weight * Number(firstTen[index]), 0);
  const remainder = sum % 11;
  if (remainder === 0) return 0;
  if (remainder === 1) return null;
  return 11 - remainder;
}

/**
 * Spaces and dashes are ignored, as the server ignores them. Fewer than eleven ASCII digits is still being typed;
 * anything else that is not eleven ASCII digits with the right check digit is invalid.
 */
export function cuitState(raw: string): CuitState {
  const digits = raw.replace(/[\s-]/g, "");
  if (/^[0-9]{0,10}$/.test(digits)) return "typing";
  if (!/^[0-9]{11}$/.test(digits)) return "invalid";
  return checkDigit(digits.slice(0, 10)) === Number(digits[10]) ? "valid" : "invalid";
}
