import type { BookedItem } from "@/shared/api/discrepancies";

interface BookedListProps {
  items: readonly BookedItem[];
  /** The id of the heading that names the list, for the table's accessible name. */
  labelledBy: string;
}

/** STUB (cd.2.11): cd.2.14 pins the list and cd.2.15 draws it. */
export function BookedList(_props: BookedListProps) {
  return null;
}
