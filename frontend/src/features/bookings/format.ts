/**
 * Formats an ISO-8601 timestamp explicitly in UTC, so the rendered instant
 * never silently depends on the browser's (or test runner's) local
 * timezone. Every timestamp this feature reads (`expires_at`, `filled_at`)
 * is produced and stored by the backend in UTC.
 */
export function formatUtcTimestamp(iso: string): string {
  const date = new Date(iso);
  const formatted = new Intl.DateTimeFormat("en-CA", {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
  return `${formatted} UTC`;
}
