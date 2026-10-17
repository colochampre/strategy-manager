import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/**
 * `GET /api/reconciliation/confirmed` (design addendum "PR 15" sections G and H, owner decision 66).
 * Quantities are JSON strings and are never converted here.
 */

export type DiscrepancyKind =
  | "ATTRIBUTABLE_SINGLE_ALLOCATION"
  | "ATTRIBUTABLE_FULL_CLOSE"
  | "AMBIGUOUS_PARTIAL_REDUCE"
  | "NO_MATCHING_ALLOCATION";

export type NeedsOwnerReason = "NOT_BOOKABLE" | "SEVERAL_ALLOCATIONS" | "NOT_BOOKED" | "REASON_UNKNOWN";

export interface AllocationRef {
  allocation_id: string;
  strategy_id: string | null;
  strategy_name: string | null;
}

export interface ConfirmedDiscrepancy {
  discrepancy_id: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  symbol: string;
  kind: DiscrepancyKind;
  reason: NeedsOwnerReason | null;
  venue_net_base: string;
  ledger_net_base: string;
  allocations: AllocationRef[];
  confirmed_at: string | null;
  last_observed_at: string;
}

export interface BookedItem {
  proposal_id: string;
  discrepancy_id: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  symbol: string;
  kind: DiscrepancyKind;
  strategy_id: string;
  strategy_name: string | null;
  allocation_id: string;
  side: string;
  quantity: string;
  fill_count: number;
  decided_at: string;
  decided_by: "automatic" | "owner";
  execution_attempt_id: string | null;
  discrepancy_open: boolean;
}

/** One answer of the route: what the badge and the page both select from. */
export interface ConfirmedReading {
  read_at: string;
  dry_run: boolean;
  needs_owner_count: number;
  needs_owner: ConfirmedDiscrepancy[];
  being_booked: ConfirmedDiscrepancy[];
  booked: BookedItem[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

/** A field the route always writes, as text or as JSON null: a MISSING field is neither and is refused. */
function isTextOrNull(value: unknown): boolean {
  return value === null || typeof value === "string";
}

/** An instant the browser can read: a time it cannot would be written as "Invalid Date" or as nothing. */
function isInstant(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

const KINDS: readonly unknown[] = [
  "ATTRIBUTABLE_SINGLE_ALLOCATION",
  "ATTRIBUTABLE_FULL_CLOSE",
  "AMBIGUOUS_PARTIAL_REDUCE",
  "NO_MATCHING_ALLOCATION",
];
const REASONS: readonly unknown[] = ["NOT_BOOKABLE", "SEVERAL_ALLOCATIONS", "NOT_BOOKED", "REASON_UNKNOWN"];
const DECIDERS: readonly unknown[] = ["automatic", "owner"];

function isAllocation(value: unknown): value is AllocationRef {
  return (
    isRecord(value) &&
    isText(value.allocation_id) &&
    isTextOrNull(value.strategy_id) &&
    isTextOrNull(value.strategy_name)
  );
}

function isDiscrepancy(value: unknown): value is ConfirmedDiscrepancy {
  return (
    isRecord(value) &&
    isText(value.discrepancy_id) &&
    isText(value.exchange) &&
    isText(value.venue) &&
    isText(value.settlement_currency) &&
    isText(value.symbol) &&
    KINDS.includes(value.kind) &&
    (value.reason === null || REASONS.includes(value.reason)) &&
    isText(value.venue_net_base) &&
    isText(value.ledger_net_base) &&
    Array.isArray(value.allocations) &&
    value.allocations.every(isAllocation) &&
    (value.confirmed_at === null || isInstant(value.confirmed_at)) &&
    isInstant(value.last_observed_at)
  );
}

function isBooked(value: unknown): value is BookedItem {
  return (
    isRecord(value) &&
    isText(value.proposal_id) &&
    isText(value.discrepancy_id) &&
    isText(value.exchange) &&
    isText(value.venue) &&
    isText(value.settlement_currency) &&
    isText(value.symbol) &&
    KINDS.includes(value.kind) &&
    isText(value.strategy_id) &&
    isTextOrNull(value.strategy_name) &&
    isText(value.allocation_id) &&
    isText(value.side) &&
    isText(value.quantity) &&
    typeof value.fill_count === "number" &&
    isInstant(value.decided_at) &&
    DECIDERS.includes(value.decided_by) &&
    isTextOrNull(value.execution_attempt_id) &&
    typeof value.discrepancy_open === "boolean"
  );
}

function isConfirmedReading(value: unknown): value is ConfirmedReading {
  return (
    isRecord(value) &&
    isInstant(value.read_at) &&
    typeof value.dry_run === "boolean" &&
    typeof value.needs_owner_count === "number" &&
    Array.isArray(value.needs_owner) &&
    value.needs_owner.every(isDiscrepancy) &&
    Array.isArray(value.being_booked) &&
    value.being_booked.every(isDiscrepancy) &&
    Array.isArray(value.booked) &&
    value.booked.every(isBooked)
  );
}

/**
 * `GET /api/reconciliation/confirmed`: the whole system, no parameter. The body is checked element by element
 * and refused WHOLE when one is bad: a body that is not this shape is an error, never an empty list (K row 8),
 * because an empty list reads as "nothing needs you". A 404 (an API that predates the route) is an error too.
 */
export async function fetchConfirmed(): Promise<ConfirmedReading> {
  const body = await apiFetch<unknown>("/reconciliation/confirmed");
  if (!isConfirmedReading(body)) {
    throw new ApiError(200, {
      detail:
        "Unexpected response shape from GET /reconciliation/confirmed: expected read_at, dry_run, needs_owner_count, needs_owner, being_booked and booked",
    });
  }
  return body;
}

/** The key the page's "Read again" button asks for. */
export const CONFIRMED_KEY = ["reconciliation", "confirmed"] as const;

const CONFIRMED_MS = 60_000;

/**
 * Query key `['reconciliation','confirmed']`: ONE key, read by the navigation's badge and by the page, so one
 * request answers both and they cannot disagree. Stale after 60 s and read again every 60 s (a state the owner
 * acts on, not a history); the window focus refetch is the client's default.
 */
export function useConfirmedDiscrepancies() {
  return useQuery({
    queryKey: CONFIRMED_KEY,
    queryFn: fetchConfirmed,
    staleTime: CONFIRMED_MS,
    refetchInterval: CONFIRMED_MS,
  });
}
