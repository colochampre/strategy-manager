const SIGNIFICANT_DIGITS = 8;
/** The table's figures keep five decimals, and at least this many significant digits when five would leave fewer. */
const TABLE_DECIMALS = 5;
const TABLE_SIGNIFICANT_FLOOR = 4;
const DECIMAL_TEXT = /^(-?)(\d+)(?:\.(\d+))?$/;

/** Adds one unit in the last place of a string of digits, carrying; "999" becomes "1000". */
function incrementDigits(digits: string): string {
  const out = digits.split("");
  for (let index = out.length - 1; index >= 0; index -= 1) {
    if (out[index] === "9") {
      out[index] = "0";
    } else {
      out[index] = String(Number(out[index]) + 1);
      return out.join("");
    }
  }
  return `1${out.join("")}`;
}

/** How many decimals a figure keeps, given its integer digits (without leading zeros) and its fraction. */
type DecimalsRule = (integer: string, fraction: string, leadingZeros: number) => number;

/**
 * The text operation both figure writers share: the server's own decimal string rounded half up on its
 * digits, with the carry, to the number of decimals `rule` allows; trailing zeros go, no exponent is
 * ever written, integer digits are never dropped, and a string that is not a plain decimal gives
 * `null`. It is not arithmetic: money is never computed in the browser (design § F, § 15).
 */
function roundedFigure(value: string, rule: DecimalsRule): string | null {
  const match = DECIMAL_TEXT.exec(value);
  if (match === null) return null;
  const sign = match[1] ?? "";
  const integer = (match[2] ?? "").replace(/^0+(?=\d)/, "");
  const fraction = match[3] ?? "";
  const leadingZeros = fraction.length - fraction.replace(/^0+/, "").length;
  if (integer === "0" && leadingZeros === fraction.length) return "0";
  const allowed = rule(integer, fraction, leadingZeros);

  const kept = fraction.slice(0, allowed);
  let digits = integer + kept;
  let integerLength = integer.length;
  if (fraction.length > allowed && (fraction[allowed] ?? "0") >= "5") {
    digits = incrementDigits(digits);
    integerLength = digits.length - kept.length;
  }
  const wholePart = digits.slice(0, integerLength);
  const fractionPart = digits.slice(integerLength).replace(/0+$/, "");
  const text = fractionPart === "" ? wholePart : `${wholePart}.${fractionPart}`;
  return text === "0" ? text : `${sign}${text}`;
}

/**
 * A stored price, size or fee as the dialog and the fills table write it: up to eight significant
 * digits and no trailing zeros, never an exponent. Integer digits are never dropped, so a large figure
 * keeps its magnitude. A string that is not a plain decimal gives `null`.
 */
export function figureText(value: string): string | null {
  return roundedFigure(value, (integer, _fraction, leadingZeros) =>
    integer !== "0" ? Math.max(0, SIGNIFICANT_DIGITS - integer.length) : leadingZeros + SIGNIFICANT_DIGITS,
  );
}

/**
 * A stored price or size as the trades table writes it, shorter than `figureText` (owner decision 46):
 * at most five decimals and no trailing zeros, and four significant digits instead when five decimals
 * would leave fewer than four, so a small price never reads 0. Never an exponent; a string that is not
 * a number gives `null`. The same text operation as `figureText`, with its rounding.
 */
export function tableFigureText(value: string): string | null {
  return roundedFigure(value, (integer, _fraction, leadingZeros) => {
    if (integer !== "0") return TABLE_DECIMALS;
    return TABLE_DECIMALS - leadingZeros < TABLE_SIGNIFICANT_FLOOR ? leadingZeros + TABLE_SIGNIFICANT_FLOOR : TABLE_DECIMALS;
  });
}

const RATE_TEXT = /^(\d+)(?:\.(\d+))?$/;
/** A rate is cut at one decimal of the percentage: three digits of the ratio, tenths of a percent. */
const RATE_DIGITS = 3;

/**
 * A served win rate as an unsigned percentage with one decimal (`0.5833333333` is `58.3%`). The digits
 * of the served string are cut at the tenth of a percent and never rounded, so only a rate of exactly one
 * reads 100.0%; the cut count is then given to `Intl` for the language's separator and sign. It is a
 * text operation, not a division, and not `percentText`, which signs every figure. A string that is not
 * a plain ratio, an exponent included, gives `null`.
 */
export function rateText(ratio: string, locale: string): string | null {
  const match = RATE_TEXT.exec(ratio);
  if (match === null) return null;
  const tenths = Number(`${match[1] ?? ""}${(match[2] ?? "").padEnd(RATE_DIGITS, "0").slice(0, RATE_DIGITS)}`);
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(tenths / 1000);
}

/**
 * An instant as a numeric calendar date in UTC, in the panel's language (`10/5/2026` in English,
 * `5/10/2026` in Spanish, for 2026-10-05): the first line of an Opened or Closed cell. Read from the
 * instant by `Intl`, never parsed from a formatted string. An instant that cannot be read is returned
 * as the server wrote it, like `dateTimeText`.
 */
export function compactDateText(iso: string, locale: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "numeric", day: "numeric", timeZone: "UTC" }).format(instant);
}

/**
 * An instant as a 24-hour `HH:mm` time in UTC, for the line below the date of an Opened or Closed
 * cell; `null` for an instant that cannot be read, so no time line is drawn for it. The language does
 * not change it, so it is written with a fixed 24-hour locale.
 */
export function clockText(iso: string): string | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" }).format(instant);
}

/** A timestamp as a calendar day in UTC, the day boundary the whole panel uses (`day_boundary: "UTC"`). */
export function dayText(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(iso));
}

/**
 * A timestamp as a UTC date and a 24-hour time (`Sep 30, 2026, 12:30`). An instant that
 * cannot be read is returned as the server wrote it: `Intl` would throw on it, and a
 * made-up date would be worse than the raw text.
 */
export function dateTimeText(iso: string, locale: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    hourCycle: "h23",
    timeZone: "UTC",
  }).format(instant);
}
