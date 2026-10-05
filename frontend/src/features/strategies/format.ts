const SIGNIFICANT_DIGITS = 8;
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

/**
 * A stored price, size or fee as the table writes it: the server's own decimal string with up to
 * eight significant digits and no trailing zeros, never an exponent. Integer digits are never
 * dropped, so a large figure keeps its magnitude. A string that is not a plain decimal gives
 * `null`. This is a text operation over the digits, not arithmetic: money is never computed in
 * the browser (design § F, § 15).
 */
export function figureText(value: string): string | null {
  const match = DECIMAL_TEXT.exec(value);
  if (match === null) return null;
  const sign = match[1] ?? "";
  const integer = (match[2] ?? "").replace(/^0+(?=\d)/, "");
  const fraction = match[3] ?? "";

  let allowed: number;
  if (integer !== "0") {
    allowed = Math.max(0, SIGNIFICANT_DIGITS - integer.length);
  } else {
    const leadingZeros = fraction.length - fraction.replace(/^0+/, "").length;
    if (leadingZeros === fraction.length) return "0";
    allowed = leadingZeros + SIGNIFICANT_DIGITS;
  }

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
 * STUB (task 9p.5.30, red): returns its argument. Green writes a stored price or size for the table: at
 * most five decimals, with a four-significant-digit floor for a small one.
 */
export function tableFigureText(value: string): string | null {
  return value;
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
