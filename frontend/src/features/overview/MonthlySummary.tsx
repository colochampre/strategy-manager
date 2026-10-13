import { useTranslation } from "react-i18next";

import { parseDecimal, percentText } from "@/shared/lib/amount-text";
import type { Excluded, MonthReturn } from "@/shared/api/types";

/**
 * How many positions a pool holds, and how many of them are dry run. A position of both origins is in `total`
 * and not in `rehearsal`.
 */
export interface OpenCount {
  total: number;
  rehearsal: number;
}

interface MonthlySummaryProps {
  monthly: readonly MonthReturn[];
  excluded: Excluded;
  /**
   * Absent: today's live-only part, "N open trades not in the curve" (the detail page). Null: the Overview while
   * its read is loading or failed, no part about open positions. A count: the Overview's part.
   */
  open?: OpenCount | null;
}

/**
 * The line under the grid: how many months were positive, the best and the
 * worst, and what the curve leaves out. A month at exactly 0% is not positive.
 */
export function MonthlySummary({ monthly, excluded, open }: MonthlySummaryProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";

  const values: number[] = [];
  for (const entry of monthly) {
    const value = parseDecimal(entry.return);
    if (value === null) {
      return (
        <p role="alert" className="text-sm text-loss">
          {t("overview.monthlyGrid.unreadable")}
        </p>
      );
    }
    values.push(value);
  }

  const parts: string[] = [];
  if (values.length > 0) {
    parts.push(
      t("overview.monthlySummary.positive", {
        count: values.length,
        positive: values.filter((value) => value > 0).length,
      }),
      t("overview.monthlySummary.best", { value: percentText(Math.max(...values), locale) }),
      t("overview.monthlySummary.worst", { value: percentText(Math.min(...values), locale) }),
    );
  }
  if (open === undefined) {
    // The detail page: today's live-only part, as it was (owner decision Q6, 2026-10-13).
    if (excluded.open_trade_count > 0) {
      parts.push(t("overview.monthlySummary.open", { count: excluded.open_trade_count }));
    }
  } else if (open !== null && open.total > 0) {
    // The Overview. A null `open` (the read is loading or failed) writes no part at all, old or new.
    parts.push(
      open.rehearsal === 0
        ? t("overview.monthlySummary.openAll", { count: open.total })
        : t("overview.monthlySummary.openWithRehearsal", { total: open.total, rehearsal: open.rehearsal }),
    );
  }
  if (excluded.no_capital_at_open > 0) {
    parts.push(t("overview.monthlySummary.noCapital", { count: excluded.no_capital_at_open }));
  }
  if (parts.length === 0) return null;

  return (
    <p data-testid="monthly-summary" className="font-mono text-[11px] text-ink-3">
      {parts.join(" · ")}
    </p>
  );
}
