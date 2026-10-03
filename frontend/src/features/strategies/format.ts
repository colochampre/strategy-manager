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
