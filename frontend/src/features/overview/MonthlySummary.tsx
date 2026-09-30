import { useTranslation } from "react-i18next";

import { parseDecimal, percentText } from "@/features/overview/format";
import type { Excluded, MonthReturn } from "@/shared/api/types";

interface MonthlySummaryProps {
  monthly: readonly MonthReturn[];
  excluded: Excluded;
}

/**
 * The line under the grid: how many months were positive, the best and the
 * worst, and what the curve leaves out. A month at exactly 0% is not positive.
 */
export function MonthlySummary({ monthly, excluded }: MonthlySummaryProps) {
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
  if (excluded.open_trade_count > 0) {
    parts.push(t("overview.monthlySummary.open", { count: excluded.open_trade_count }));
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
