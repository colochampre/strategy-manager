/** A timestamp as a calendar day in UTC, the day boundary the whole panel uses (`day_boundary: "UTC"`). */
export function dayText(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(iso));
}
