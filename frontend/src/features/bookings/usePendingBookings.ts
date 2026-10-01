import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { BookingProposal } from "@/shared/api/types";

async function fetchPendingBookings(): Promise<BookingProposal[]> {
  const body = await apiFetch<unknown>("/reconciliation/bookings?state=pending");
  // Never trust a 200's body shape -- a malformed payload (e.g. `{items:
  // []}` instead of a bare array) must render as the error state, never as
  // "no pending bookings" (carried forward from the unit 9a review).
  if (!Array.isArray(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /reconciliation/bookings: expected an array",
    });
  }
  return body as BookingProposal[];
}

/**
 * Query key `['bookings','pending']`. The list and the decision rail's count
 * read it through this one hook, so they share one request and can never
 * disagree about what is pending.
 */
export function usePendingBookings() {
  return useQuery({
    queryKey: ["bookings", "pending"],
    queryFn: fetchPendingBookings,
  });
}
