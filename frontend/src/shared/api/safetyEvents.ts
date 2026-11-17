import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

export type SafetyEventKind =
  | "STOP_FIRED"
  | "STOP_FAILED_CLOSED"
  | "STRATEGY_STOPPED_CLOSED"
  | "MANUAL_CLOSE"
  | "OPENING_REFUSED_LEVERAGE_CAP";

export interface SafetyEvent {
  id: string;
  /** Typed as text: a kind this build does not know is shown with a neutral fallback, never refused. */
  kind: string;
  strategy_id: string;
  strategy_name: string;
  allocation_id: string | null;
  exchange: string;
  venue: string;
  symbol: string;
  occurred_at: string;
  /** Every value is a string; which keys exist depends on the kind, and a missing one is tolerated by the page. */
  detail: Record<string, string>;
}

export interface SafetyEventsAnswer {
  events: SafetyEvent[];
}

export const SAFETY_EVENTS_KEY = ["safety-events"] as const;

const SAFETY_EVENTS_MS = 60_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function isInstant(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

function isEvent(value: unknown): value is SafetyEvent {
  return (
    isRecord(value) &&
    isText(value.id) &&
    isText(value.kind) &&
    isText(value.strategy_id) &&
    isText(value.strategy_name) &&
    (value.allocation_id === null || isText(value.allocation_id)) &&
    isText(value.exchange) &&
    isText(value.venue) &&
    isText(value.symbol) &&
    isInstant(value.occurred_at) &&
    isRecord(value.detail) &&
    Object.values(value.detail).every(isText)
  );
}

/**
 * `GET /api/safety-events`: the signed-in user's own events, newest first, at most 100. The body is checked
 * element by element and refused WHOLE when one is bad: an error on screen, never an empty list, because an
 * empty list reads as "nothing happened to your positions". A kind or a detail key this build does not know
 * is NOT refused; the page falls back for it.
 */
export async function fetchSafetyEvents(): Promise<SafetyEventsAnswer> {
  const body = await apiFetch<unknown>("/safety-events");
  if (!isRecord(body) || !Array.isArray(body.events) || !body.events.every(isEvent)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /safety-events: expected events" });
  }
  return { events: body.events };
}

export function useSafetyEvents() {
  return useQuery({
    queryKey: SAFETY_EVENTS_KEY,
    queryFn: fetchSafetyEvents,
    staleTime: SAFETY_EVENTS_MS,
    refetchInterval: SAFETY_EVENTS_MS,
  });
}
