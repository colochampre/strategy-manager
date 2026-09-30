import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { parseDecimal, percentText, toneClass } from "@/features/overview/format";
import type { MonthReturn } from "@/shared/api/types";
import { gridBand } from "@/shared/charts/scale";
import { cn } from "@/shared/lib/cn";

interface MonthlyGridProps {
  /** One entry per UTC month that has a closed day; a month with none is absent. */
  monthly: readonly MonthReturn[];
}

/**
 * Band 0 is exactly zero (the neutral base); bands 1 to 6 are 2.5 points each on
 * a fixed +-15% scale. Every class is written out whole so Tailwind can see it.
 */
const GAIN_BANDS = [
  "bg-rule-soft",
  "bg-gain-1",
  "bg-gain-2",
  "bg-gain-3",
  "bg-gain-4",
  "bg-gain-5",
  "bg-gain-6",
] as const;
const LOSS_BANDS = [
  "bg-rule-soft",
  "bg-loss-1",
  "bg-loss-2",
  "bg-loss-3",
  "bg-loss-4",
  "bg-loss-5",
  "bg-loss-6",
] as const;
/** From this band the fill is dark enough that the text must flip to the ground colour. */
const FIRST_CONTRAST_BAND = 4;

/** The rows shown before the owner asks for the earlier ones (decision 34). */
const VISIBLE_YEARS = 3;

const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as const;

/** year -> month (1 to 12) -> return; `null` when any entry is not a readable month. */
function readMonths(monthly: readonly MonthReturn[]): Map<number, Map<number, number>> | null {
  const years = new Map<number, Map<number, number>>();
  for (const entry of monthly) {
    const value = parseDecimal(entry.return);
    const isMonth =
      Number.isInteger(entry.year) &&
      Number.isInteger(entry.month) &&
      entry.month >= 1 &&
      entry.month <= 12;
    if (value === null || !isMonth) return null;
    const row = years.get(entry.year) ?? new Map<number, number>();
    row.set(entry.month, value);
    years.set(entry.year, row);
  }
  return years;
}

/**
 * The compounded return of a year: the product of its months, less one. A month
 * with no closed trade leaves the index where it was, so it contributes 1.
 * Display only: it is a ratio, never money.
 */
function yearReturn(row: ReadonlyMap<number, number>): number {
  let index = 1;
  for (const value of row.values()) index *= 1 + value;
  return index - 1;
}

export function MonthlyGrid({ monthly }: MonthlyGridProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const titleId = useId();
  const tableRegionId = useId();
  const [showEarlier, setShowEarlier] = useState(false);
  const years = readMonths(monthly);

  // Calendar months are named in UTC: west of UTC, local midnight on the 1st is the month before.
  const monthName = (style: "long" | "narrow") => {
    const format = new Intl.DateTimeFormat(locale, { month: style, timeZone: "UTC" });
    return (month: number) => format.format(new Date(Date.UTC(2000, month - 1, 1)));
  };
  const longName = monthName("long");
  const narrowName = monthName("narrow");

  const title = (
    <h2 id={titleId} className="font-display text-base font-semibold text-ink">
      {t("overview.monthlyGrid.title")}
    </h2>
  );

  if (years === null) {
    return (
      <section aria-labelledby={titleId} className="flex flex-col gap-2.5">
        {title}
        <p role="alert" className="text-sm text-loss">
          {t("overview.monthlyGrid.unreadable")}
        </p>
      </section>
    );
  }

  if (years.size === 0) {
    return (
      <section aria-labelledby={titleId} className="flex flex-col gap-2.5">
        {title}
        <p className="text-sm text-ink-3">{t("overview.monthlyGrid.empty")}</p>
      </section>
    );
  }

  // Newest first. Only the rows are cut: every year keeps all of its months, so its total is the year's.
  const allRows = [...years.entries()].sort(([a], [b]) => b - a);
  const hasEarlier = allRows.length > VISIBLE_YEARS;
  const rows = showEarlier ? allRows : allRows.slice(0, VISIBLE_YEARS);

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2.5">
      {title}
      <div id={tableRegionId} className="overflow-x-auto">
        <table
          aria-labelledby={titleId}
          className="w-full min-w-[42rem] table-fixed border-separate border-spacing-1 font-mono text-[11px] tabular-nums"
        >
          <thead>
            <tr>
              <td className="w-12" />
              {MONTHS.map((month) => (
                <th
                  key={month}
                  scope="col"
                  aria-label={longName(month)}
                  className="font-normal text-ink-3"
                >
                  {narrowName(month)}
                </th>
              ))}
              <th scope="col" className="w-16 font-normal text-ink-3">
                {t("overview.monthlyGrid.year")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([year, row]) => {
              const total = yearReturn(row);
              return (
                <tr key={year}>
                  <th scope="row" className="text-left font-normal text-ink-2">
                    {year}
                  </th>
                  {MONTHS.map((month) => {
                    const value = row.get(month);
                    const label = `${longName(month)} ${year}`;
                    if (value === undefined) {
                      return (
                        <td
                          key={month}
                          data-testid={`month-${year}-${month}`}
                          aria-label={`${label}: ${t("overview.monthlyGrid.noTrades")}`}
                          className="h-10 rounded-[3px] border border-dashed border-rule"
                        />
                      );
                    }
                    const band = gridBand(value);
                    return (
                      <td
                        key={month}
                        data-testid={`month-${year}-${month}`}
                        aria-label={`${label}: ${percentText(value, locale)}`}
                        className={cn(
                          "h-10 rounded-[3px] text-center",
                          (value < 0 ? LOSS_BANDS : GAIN_BANDS)[band],
                          band >= FIRST_CONTRAST_BAND ? "font-semibold text-ground" : "text-ink",
                        )}
                      >
                        {percentText(value, locale, false)}
                      </td>
                    );
                  })}
                  <td
                    data-testid={`year-${year}`}
                    className={cn("text-center font-semibold", toneClass(total))}
                  >
                    {percentText(total, locale)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hasEarlier && (
        <button
          type="button"
          aria-expanded={showEarlier}
          aria-controls={tableRegionId}
          onClick={() => setShowEarlier(!showEarlier)}
          className="min-h-11 self-start rounded-md px-1 font-mono text-[11px] text-ink-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-gain"
        >
          {showEarlier ? t("overview.monthlyGrid.hideEarlier") : t("overview.monthlyGrid.showEarlier")}
        </button>
      )}
    </section>
  );
}
