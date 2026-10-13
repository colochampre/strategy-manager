/**
 * Display-only number handling for the ledger line and the monthly grid.
 *
 * The server writes money and ratios as decimal strings (`shared/api/types.ts`).
 * They are parsed here for one purpose, to hand them to `Intl.NumberFormat`, and
 * nothing in the overview ever adds, subtracts or converts money (CLAUDE.md,
 * rule 7): every figure is formatted in its own pool's settlement currency and
 * two pools are never combined.
 */

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** Decimal places shown per settlement currency; a coin-margined pool needs more than two. */
const AMOUNT_DECIMALS: Readonly<Record<string, number>> = { BTC: 8, ETH: 8 };
const DEFAULT_AMOUNT_DECIMALS = 2;

/** How many decimals a pool's settlement currency is shown with: the one table the trades and the share use. */
export function amountDecimals(currency: string): number {
  return AMOUNT_DECIMALS[currency] ?? DEFAULT_AMOUNT_DECIMALS;
}

/** The server's plain-notation decimal as a number, or `null` for anything else (never NaN). */
export function parseDecimal(value: string): number | null {
  return DECIMAL.test(value) ? Number(value) : null;
}

/**
 * A money figure in the pool's currency, with no currency symbol: USDT is not an
 * ISO 4217 code, so `style: "currency"` would throw. The currency is written
 * beside the figure by the caller.
 */
export function amountText(amount: number, currency: string, locale: string, signed = false): string {
  const digits = amountDecimals(currency);
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(amount);
}

/**
 * A ratio as a signed percentage with one decimal (0.031 is `+3.1%`). Without
 * the symbol the number alone is returned, for a cell too narrow to hold it.
 */
export function percentText(ratio: number, locale: string, symbol = true): string {
  const parts = new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: "exceptZero",
  }).formatToParts(ratio);
  return parts
    .filter((part) => symbol || (part.type !== "percentSign" && part.type !== "literal"))
    .map((part) => part.value)
    .join("");
}

/** Gain teal above zero, loss ember below it, plain secondary ink at exactly zero. */
export function toneClass(value: number): string {
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-ink-2";
}
