import { useTranslation } from "react-i18next";

import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import type { OpenCount } from "@/features/overview/MonthlySummary";
import type { Excluded, MonthReturn } from "@/shared/api/types";
import { gridStep } from "@/shared/charts/scale";
import { parseDecimal, percentText } from "@/shared/lib/amount-text";
import { Card } from "@/shared/ui/Card";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

interface MonthlyCardProps {
  monthly: readonly MonthReturn[];
  excluded: Excluded;
  /** The Overview's count of open positions, for the summary line; see `MonthlySummary`. */
  open?: OpenCount | null;
}

/** Every month's return, or null when there is none or one cannot be read: the grid says which. */
function readValues(monthly: readonly MonthReturn[]): number[] | null {
  const values: number[] = [];
  for (const entry of monthly) {
    const value = parseDecimal(entry.return);
    if (value === null) return null;
    values.push(value);
  }
  return values.length === 0 ? null : values;
}

/** The middle month; with an even count, the mean of the two middle ones. */
function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const upper = sorted[middle] ?? 0;
  return sorted.length % 2 === 1 ? upper : ((sorted[middle - 1] ?? 0) + upper) / 2;
}

/**
 * The one "Monthly performance" card (ex1), on the Overview and on both strategy pages alike (L29): the grid, then its
 * summary line right under it. Beside the title, the median month, which one outsized month does not pull as a mean
 * would, and behind an (i) the grid's colour scale, which follows its widest month (L35).
 */
export function MonthlyCard({ monthly, excluded, open }: MonthlyCardProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const info = useInfoDisclosure();
  const values = readValues(monthly);
  const step = values === null ? null : gridStep(values);
  const points = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const reach = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 2 });

  return (
    <Card
      title={t("overview.card.monthly")}
      {...(values === null
        ? {}
        : {
            action: (
              <div className="flex items-center gap-2">
                <InfoButton disclosure={info} label={t("overview.card.monthlyScaleInfo")} />
                <span data-testid="monthly-median" className="text-[12.5px] text-ink-3">
                  {t("overview.card.median", { value: percentText(median(values), locale), count: values.length })}
                </span>
              </div>
            ),
          })}
    >
      <div className="flex flex-col gap-3">
        {step !== null && (
          <InfoText disclosure={info}>
            <p className="text-sm text-ink-2">
              {t("overview.card.monthlyScale", {
                count: Number((step * 100).toFixed(2)),
                step: points.format(step * 100),
                top: reach.format(step * 6),
              })}
            </p>
          </InfoText>
        )}
        <div className="flex flex-col">
          <MonthlyGrid monthly={monthly} />
          <MonthlySummary monthly={monthly} excluded={excluded} {...(open === undefined ? {} : { open })} />
        </div>
      </div>
    </Card>
  );
}
