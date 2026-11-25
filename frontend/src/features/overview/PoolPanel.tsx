import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { HeaderCard } from "@/features/overview/HeaderCard";
import { MonthlyCard } from "@/features/overview/MonthlyCard";
import type { OpenCount } from "@/features/overview/MonthlySummary";
import { RANGES } from "@/features/overview/RangeSelector";
import { useRangeStore } from "@/features/overview/range-store";
import { ReturnChart } from "@/features/overview/ReturnChart";
import { PoolOpenPositions } from "@/features/positions/PoolOpenPositions";
import { usePoolPerformance } from "@/shared/api/performance";
import { ofPool, useOpenPositions } from "@/shared/api/positions";
import type { OpenState } from "@/shared/api/positions";
import type { Pool } from "@/shared/api/types";
import { Card } from "@/shared/ui/Card";
import { Segmented } from "@/shared/ui/Segmented";

interface PoolPanelProps {
  pool: Pool;
  /** The exchange has this one pool only: the header card says so instead of naming the venue. */
  sole?: boolean;
}

/** `2026-09-30T10:00:00+00:00` as a short UTC date and time; the server's clock is UTC. */
function observedAtText(observedAt: string, locale: string): string {
  const instant = new Date(observedAt);
  if (Number.isNaN(instant.getTime())) return observedAt;
  const text = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(instant);
  return `${text} UTC`;
}

/** The pool's own positions and how many are dry run; a position of both origins is counted in the first only. */
function openCountOf(answer: OpenState, pool: Pool): OpenCount {
  const mine = ofPool(answer, pool).positions;
  return { total: mine.length, rehearsal: mine.filter((position) => position.origin === "rehearsal").length };
}

/**
 * One capital pool, in its own settlement currency and never merged with another (rule 7): the header card, then
 * "Compounded return", "Monthly performance" and "Open positions", each a card of its own (ex1). It fetches its own
 * report once, and every range arrives in that one body, so the selector only chooses which window of the curve the
 * chart draws: the card's figures are all time. A failing pool shows its own error and leaves its neighbours alone.
 *
 * The available balance is the pools row's `balance.available`: the performance body does not carry it.
 *
 * Nothing sits between the chart and the month grid: the panel takes no slot for a caller's node.
 */
export function PoolPanel({ pool, sole = false }: PoolPanelProps) {
  const { t, i18n } = useTranslation();
  const performance = usePoolPerformance(pool.exchange, pool.venue, pool.settlement_currency);
  const range = useRangeStore((state) => state.range);
  const setRange = useRangeStore((state) => state.setRange);
  const staleBalance = pool.balance !== null && pool.balance.stale ? pool.balance : null;
  const report = performance.status === "success" ? performance.data : null;
  // The same query as the list's (one request): null while the first read is loading or has failed, so the
  // summary writes no part about open positions; the pool's own positions only (rule 7).
  const answer = useOpenPositions().data;
  const openCount = answer === undefined ? null : openCountOf(answer, pool);

  let status: ReactNode = null;
  if (performance.status === "pending") {
    status = (
      <p role="status" className="text-sm text-ink-3">
        {t("overview.pool.loading")}
      </p>
    );
  } else if (performance.status === "error") {
    status = (
      <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
        {t("overview.pool.error")}
      </p>
    );
  } else if (report === null) {
    status = (
      <p role="status" className="text-sm text-ink-3">
        {t("overview.pool.noReport")}
      </p>
    );
  }

  return (
    <section
      data-testid="pool-panel"
      aria-label={`${pool.exchange} · ${pool.venue} · ${pool.settlement_currency}`}
      className="flex w-full min-w-0 flex-col gap-4"
    >
      {/* A stale balance says so behind an (i) right of the balance's label, not on its own row. */}
      <HeaderCard
        pool={pool}
        sole={sole}
        balanceInfo={
          staleBalance === null
            ? undefined
            : {
                label: t("overview.pool.staleInfo"),
                text: t("overview.pool.stale", {
                  time: observedAtText(staleBalance.observed_at, i18n.resolvedLanguage ?? "en"),
                }),
              }
        }
        report={report}
        status={status}
        asOf={performance.dataUpdatedAt}
        openCount={openCount === null ? null : openCount.total}
      />
      {report !== null && (
        <>
          <Card
            title={t("overview.card.compound")}
            action={
              <Segmented
                size="sm"
                label={t("overview.range.label")}
                options={RANGES.map((name) => ({ value: name, label: t(`overview.range.${name}`) }))}
                value={range}
                onChange={setRange}
              />
            }
          >
            <ReturnChart
              bare
              curve={report.curve}
              origin={report.origin ?? null}
              range={range}
              asOf={performance.dataUpdatedAt}
            />
          </Card>
          <MonthlyCard monthly={report.monthly} excluded={report.excluded} open={openCount} />
        </>
      )}
      {/* Outside the report condition: a pool whose report is missing or failed can still hold a position (design § K row 24). */}
      <PoolOpenPositions pool={pool} />
    </section>
  );
}
