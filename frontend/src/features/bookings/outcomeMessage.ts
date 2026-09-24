import { ApiError } from "@/shared/api/client";

const KNOWN_OUTCOME_KEYS = new Set([
  "ALREADY_DECIDED",
  "SUPERSEDED",
  "EXPIRED",
  "DRY_RUN_REFUSED",
  "REASON_REQUIRED",
]);

/**
 * Maps a settled mutation's error to the specific i18n outcome key when the
 * backend named one -- a 409 ALREADY_DECIDED/SUPERSEDED/EXPIRED, a 503
 * DRY_RUN_REFUSED, or a 422 REASON_REQUIRED -- so the operator always sees
 * what actually happened, never a generic message for those. Anything else
 * (a 404, a network failure, an unrecognised outcome) falls back to one
 * generic i18n key: a 409/503/422 is never mistaken for success, and a 404
 * or network failure is never mistaken for one of those specific outcomes
 * (design.md § 12, unit 9b binding requirement 3).
 */
export function outcomeMessageKey(error: unknown): string {
  if (error instanceof ApiError && error.outcome !== undefined && KNOWN_OUTCOME_KEYS.has(error.outcome)) {
    return `bookings.outcomes.${error.outcome}`;
  }
  return "bookings.dialogs.genericError";
}
