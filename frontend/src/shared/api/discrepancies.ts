import { useQuery } from "@tanstack/react-query";

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

/** The key the page's "Read again" button asks for. */
export const CONFIRMED_KEY = ["reconciliation", "confirmed"] as const;

// STUB (cd.2.1): answers an empty reading without asking the server. cd.2.5 replaces it.
export async function fetchConfirmed(): Promise<ConfirmedReading> {
  return { read_at: "", dry_run: false, needs_owner_count: 0, needs_owner: [], being_booked: [], booked: [] };
}

// STUB (cd.2.1): cd.2.5 gives it the refetch interval.
export function useConfirmedDiscrepancies() {
  return useQuery({ queryKey: CONFIRMED_KEY, queryFn: fetchConfirmed });
}
