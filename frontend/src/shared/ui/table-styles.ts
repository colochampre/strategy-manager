/**
 * The prototype's boxed table (`.tbl-w`), shared by every table of the panel's cards (L16, L30): a 1 px rule
 * around it, 8 px corners, and a sideways scroll inside the box when the card is narrower than its columns.
 */
export const TABLE_BOX = "overflow-x-auto rounded-lg border border-rule";

/** `.tbl-w th`: 12.5 px tinted headings in words, padded 10 / 12 px. */
export const TABLE_HEAD =
  "whitespace-nowrap border-b border-rule bg-ground px-3 py-2.5 text-left text-[12.5px] font-medium text-ink-3";

/** `.tbl-w td`: 13 px cells padded 11 / 12 px, one line high. */
export const TABLE_CELL = "whitespace-nowrap border-b border-rule-soft px-3 py-[11px] text-[13px]";

/** Previous and Next under a paged table (the closed trades, the users): a 44 px touch target, dimmed when it cannot move. */
export const PAGER_BUTTON =
  "min-h-11 rounded-lg border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50";
