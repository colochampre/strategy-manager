import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";

export type DiscrepancyVariant = "needsYou" | "beingBooked";

interface DiscrepancyItemProps {
  item: ConfirmedDiscrepancy;
  variant: DiscrepancyVariant;
  /** The `read_at` of the answer the item belongs to: a time on another UTC day is written with its date. */
  readAt: string;
}

/** STUB (cd.2.11): cd.2.12 pins the item and cd.2.13 draws it. */
export function DiscrepancyItem(_props: DiscrepancyItemProps) {
  return null;
}
