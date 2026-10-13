import type { BookingProposal } from "@/shared/api/types";

/**
 * The ONE rule for "a pending proposal names this position": the proposal is still PENDING, and it is for the
 * position's allocation and for the discrepancy its venue mark carries. The list's venue chip and the venue
 * line both read it, so they cannot disagree about whether the link to the pending decision is drawn.
 */
export function pendingProposalNames(
  proposals: readonly Pick<BookingProposal, "state" | "allocation_id" | "discrepancy_id">[],
  allocationId: string,
  discrepancyId: string,
): boolean {
  return proposals.some(
    (proposal) => proposal.state === "PENDING" && proposal.allocation_id === allocationId && proposal.discrepancy_id === discrepancyId,
  );
}
