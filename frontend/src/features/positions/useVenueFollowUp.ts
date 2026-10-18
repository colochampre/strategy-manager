import { useTranslation } from "react-i18next";

import { useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";

/** What follows a venue mark that has found its discrepancy: the words of its state, when it has any, and the link. */
export interface VenueFollowUp {
  /** "being booked automatically", or the words of the reason; null for a reason with no sentence of its own. */
  words: string | null;
  /** The item on the discrepancies page, which the page scrolls to by its hash. */
  to: { pathname: string; hash: string };
}

type Translate = ReturnType<typeof useTranslation>["t"];

/**
 * The words of a discrepancy that needs the owner: its reason when the reason has a sentence of its own, and
 * otherwise the kind when the kind has one (`AMBIGUOUS_PARTIAL_REDUCE` arrives with the reason `NOT_BOOKABLE`).
 * Every other case has no words, and the line draws only its link: an item is never left without its link.
 */
function reasonWords(item: ConfirmedDiscrepancy, t: Translate): string | null {
  if (item.reason === "NOT_BOOKED") return t("positions.venue.line.reason.NOT_BOOKED");
  if (item.reason === "SEVERAL_ALLOCATIONS") return t("positions.venue.line.reason.SEVERAL_ALLOCATIONS");
  if (item.kind === "AMBIGUOUS_PARTIAL_REDUCE") return t("positions.venue.line.reason.AMBIGUOUS_PARTIAL_REDUCE");
  return null;
}

/**
 * The ONE place the two venue marks (the line under a position and the chip on a strategy's row) find their
 * discrepancy: by the `discrepancy_id` of the position's disagreement, in `needs_owner` or `being_booked` of the
 * one query `useConfirmedDiscrepancies` (owner decision 66 Q8; design addendum "PR 15" § H). The symbols of the
 * position and of the discrepancy are spelled differently and are never compared.
 *
 * It returns null, and so makes no claim and draws no link, while the query loads, after it failed with nothing
 * read yet, and for an id in neither list (one the scan resolved between the two reads): until the lists are READ
 * a link would be a guess and the words a claim nobody checked (design § K rows 15 and 22).
 */
export function useVenueFollowUp(discrepancyId: string): VenueFollowUp | null {
  const { t } = useTranslation();
  const confirmed = useConfirmedDiscrepancies();
  if (confirmed.data === undefined) return null;

  const to = { pathname: "/discrepancies", hash: `#discrepancy-${discrepancyId}` };
  const owned = confirmed.data.needs_owner.find((item) => item.discrepancy_id === discrepancyId);
  if (owned !== undefined) return { words: reasonWords(owned, t), to };
  // Under dry run the discrepancies page draws no list, so CONFIRMED rows left from a live period are neither
  // being booked (nothing books in dry run) nor anything the link could reach (cd.f10).
  if (confirmed.data.dry_run) return null;
  const booking = confirmed.data.being_booked.some((item) => item.discrepancy_id === discrepancyId);
  if (booking) return { words: t("positions.venue.line.beingBooked"), to };
  return null;
}
