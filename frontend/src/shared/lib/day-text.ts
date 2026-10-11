/**
 * A timestamp as a calendar day in UTC, the day boundary the whole panel uses
 * (`day_boundary: "UTC"`), in the given locale's medium date style. It lives in
 * `shared/` because the strategies and the Settings features both write dates
 * and a feature must not import from another feature.
 */
export function dayText(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(iso));
}
