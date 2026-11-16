import { useTranslation } from "react-i18next";

import type { ApiError } from "@/shared/api/client";

export interface Reason {
  key: string;
  values: Record<string, string | number>;
}

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/**
 * What an `OPEN_POSITION` refusal says still holds the strategy: the symbols it
 * holds, and how many allocations, live reservations and in-flight attempts it
 * has (the ids themselves tell the owner nothing). A body in which any of the
 * four is missing or is not a list of strings yields no lines at all: the main
 * sentence is then shown alone, never a half-trusted list.
 *
 * Archive and disable answer the same body, so both dialogs read it here.
 */
export function openPositionReasons(error: ApiError): Reason[] {
  const { symbols, allocations, live_reservations: reservations, in_flight_attempts: attempts } = error.fields ?? {};
  if (!isStrings(symbols) || !isStrings(allocations) || !isStrings(reservations) || !isStrings(attempts)) return [];
  const reasons: Reason[] = [];
  if (symbols.length > 0) reasons.push({ key: "symbols", values: { symbols: symbols.join(", ") } });
  if (allocations.length > 0) reasons.push({ key: "allocations", values: { count: allocations.length } });
  if (reservations.length > 0) reasons.push({ key: "liveReservations", values: { count: reservations.length } });
  if (attempts.length > 0) reasons.push({ key: "inFlightAttempts", values: { count: attempts.length } });
  return reasons;
}

/** The reasons as a list; nothing at all when there are none. */
export function OpenPositionReasonList({ reasons }: { reasons: Reason[] }) {
  const { t } = useTranslation();
  if (reasons.length === 0) return null;
  return (
    <ul className="list-disc pl-5 text-xs">
      {reasons.map((reason) => (
        <li key={reason.key}>{t(`strategies.archive.reasons.${reason.key}`, reason.values)}</li>
      ))}
    </ul>
  );
}
