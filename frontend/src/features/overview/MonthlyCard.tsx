import { useTranslation } from "react-i18next";

import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import type { OpenCount } from "@/features/overview/MonthlySummary";
import type { Excluded, MonthReturn } from "@/shared/api/types";
import { Card } from "@/shared/ui/Card";

interface MonthlyCardProps {
  monthly: readonly MonthReturn[];
  excluded: Excluded;
  /** The Overview's count of open positions, for the summary line; see `MonthlySummary`. */
  open?: OpenCount | null;
}

/**
 * The one "Monthly performance" card (ex1), on the Overview and on both strategy pages alike (L29): the grid, then its
 * summary line right under it, with the grid's fixed colour scale beside the title.
 */
export function MonthlyCard({ monthly, excluded, open }: MonthlyCardProps) {
  const { t } = useTranslation();
  return (
    <Card
      title={t("overview.card.monthly")}
      action={<span className="text-[12.5px] text-ink-3">{t("overview.card.monthlyScale")}</span>}
    >
      <div className="flex flex-col">
        <MonthlyGrid monthly={monthly} />
        <MonthlySummary monthly={monthly} excluded={excluded} {...(open === undefined ? {} : { open })} />
      </div>
    </Card>
  );
}
