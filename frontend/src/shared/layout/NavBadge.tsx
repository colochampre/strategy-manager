import { useTranslation } from "react-i18next";

import { useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import { cn } from "@/shared/lib/cn";

interface NavBadgeProps {
  /**
   * Lift the badge to the top-right corner of its cell. The phone's bottom bar has no room beside a label as
   * long as "Discrepancias"; the side rail leaves it in the line of its label.
   */
  corner?: boolean;
}

/**
 * The count of the confirmed discrepancies that need the owner, red (`loss`) with its number, beside the
 * Discrepancies item of BOTH navigations. It reads the page's own query, so the two cannot disagree. It counts
 * the items of `needs_owner` and nothing else, and draws nothing while the read is loading, after a first
 * failed read (the page says it; a badge that said "failed" would be a permanent alarm), at zero, and when
 * `dry_run` is true (note N3). After a failed refresh the query keeps its last data, so the last count stays.
 * The number is decorative; a visually hidden span carries the words, which are the item's accessible name.
 */
export function NavBadge({ corner = false }: NavBadgeProps) {
  const { t } = useTranslation();
  const { data } = useConfirmedDiscrepancies();
  if (data === undefined || data.dry_run) return null;
  const count = data.needs_owner.length;
  if (count === 0) return null;

  return (
    <>
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex flex-none items-center justify-center rounded-full bg-loss font-mono font-semibold leading-none tabular-nums text-ground",
          corner ? "absolute right-1 top-1 h-4 min-w-[18px] px-1.5 text-[10px]" : "h-[18px] min-w-5 px-1.5 text-[11px]",
        )}
      >
        {count}
      </span>
      <span className="sr-only">, {t("discrepancies.badgeName", { count })}</span>
    </>
  );
}
