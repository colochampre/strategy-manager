import { figureText } from "@/shared/lib/figure-text";

const PLAIN_DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;

/** The value times ten to the power of `scale`, exactly, or `null` for a text that is not a plain decimal. */
function scaled(value: string, scale: number): bigint | null {
  const match = PLAIN_DECIMAL.exec(value);
  if (match === null) return null;
  const fraction = (match[3] ?? "").padEnd(scale, "0");
  const units = BigInt(`${match[2] ?? "0"}${fraction}`);
  return match[1] === "-" ? -units : units;
}

function scaleOf(value: string): number {
  return PLAIN_DECIMAL.exec(value)?.[3]?.length ?? 0;
}

/**
 * The venue's net minus the ledger's, as an exact signed decimal string (`-0.5`, `12`, `-0.82`): integer
 * arithmetic on the served digits, never a float, so `0.1 - 0.3` is `-0.2`. `null` when either net is not a
 * plain decimal. The sign of a positive difference is added by `signedFigure`.
 */
export function netDifference(venue: string, ledger: string): string | null {
  const scale = Math.max(scaleOf(venue), scaleOf(ledger));
  const a = scaled(venue, scale);
  const b = scaled(ledger, scale);
  if (a === null || b === null) return null;
  const difference = a - b;
  const negative = difference < 0n;
  const digits = (negative ? -difference : difference).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale).replace(/0+$/, "");
  const text = fraction === "" ? whole : `${whole}.${fraction}`;
  return negative && text !== "0" ? `-${text}` : text;
}

/** The decimal separator the language writes: a comma in Spanish, a point in English. */
function decimalSeparator(locale: string): string {
  return new Intl.NumberFormat(locale).formatToParts(1.1).find((part) => part.type === "decimal")?.value ?? ".";
}

/**
 * A served quantity as the page writes it: up to eight significant digits and no trailing zeros (`figureText`),
 * with the language's decimal separator. A text it cannot read is written as the server sent it.
 */
export function quantityText(value: string, locale: string): string {
  const text = figureText(value) ?? value;
  return text.replace(".", decimalSeparator(locale));
}

/** `quantityText` with an explicit `+` before a positive figure, for a difference. */
export function signedQuantityText(value: string, locale: string): string {
  const text = quantityText(value, locale);
  return /^\d/.test(text) && Number(value) > 0 ? `+${text}` : text;
}

/**
 * The base currency of a symbol, read off the venue's bare spelling (`SOLUSDT` in `USDT` is `SOL`). `null`
 * when the symbol does not end with the settlement currency: no unit is better than a wrong one.
 */
export function baseCurrencyOf(symbol: string, settlementCurrency: string): string | null {
  if (!symbol.endsWith(settlementCurrency) || symbol.length === settlementCurrency.length) return null;
  return symbol.slice(0, symbol.length - settlementCurrency.length);
}
