import { Eye, EyeOff } from "lucide-react";
import type { ReactNode } from "react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { PoolEyebrow } from "@/features/overview/PoolEyebrow";
import { Sparkline } from "@/features/overview/Sparkline";
import type { Pool, PoolPerformance } from "@/shared/api/types";
import { amountText, parseDecimal, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { Masked, useHidden } from "@/shared/hidden/Masked";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

/** The window the sparkline and its return cover, and the range summary that carries that return. */
const SPARK_DAYS = 30;
const SPARK_RANGE = "30D";
const NO_FIGURE = "—";

interface HeaderCardProps {
  pool: Pool;
  /** The exchange has this one pool only. */
  sole: boolean;
  /** The note behind the balance's (i), only while the snapshot is stale. */
  balanceInfo: { label: string; text: string } | undefined;
  /** The report, once read; the right side and the four figures wait for it. */
  report: PoolPerformance | null;
  /** What the right side says while there is no report: loading, failed, none yet. */
  status: ReactNode;
  /** When the report was read (ms): the "now" the sparkline's window ends on. */
  asOf: number;
  /** How many positions the pool holds; null while that read is loading or has failed, never a zero. */
  openCount: number | null;
}

/** One of the four figures of the row under the card, `className` carrying its rules (two a row on a phone, four from `md`). */
function Stat({ label, testId, className, children }: { label: string; testId: string; className: string; children: ReactNode }) {
  return (
    <div className={cn("px-4 py-3 md:px-6 md:pb-[18px] md:pt-4", className)}>
      <dt className="mb-1 text-[12.5px] text-ink-3">{label}</dt>
      <dd data-testid={testId} className="font-mono text-xl font-medium">
        {children}
      </dd>
    </div>
  );
}

/** The currency beside a figure: 12 px, quiet, 4 px apart (`.stat .u`). */
function StatUnit({ currency }: { currency: string }) {
  return <span className="ml-1 font-sans text-xs font-normal text-ink-3">{currency}</span>;
}

/**
 * The dashboard's first card for one pool (ex1, S8): on the left the available balance with the eye that hides every
 * balance of the panel (S1), the pool and the capital in positions; on the right the last 30 days as a sparkline
 * with their return; under them four figures of the whole history. Everything is in the pool's own settlement
 * currency and never merged with another pool's (rule 7). Figures are parsed only to be formatted; nothing is
 * computed (CLAUDE.md, rule 7).
 */
export function HeaderCard({ pool, sole, balanceInfo, report, status, asOf, openCount }: HeaderCardProps) {
  const { t, i18n } = useTranslation();
  const labelId = useId();
  const disclosure = useInfoDisclosure();
  const hidden = useHidden();
  const toggle = useHiddenStore((state) => state.toggle);
  const locale = i18n.resolvedLanguage ?? "en";
  const currency = pool.settlement_currency;

  const available = pool.balance === null ? null : parseDecimal(pool.balance.available);
  const reserved = parseDecimal(pool.reserved);
  const EyeIcon = hidden ? EyeOff : Eye;

  return (
    <section
      data-testid="header-card"
      aria-labelledby={labelId}
      className="rounded-[10px] border border-rule bg-panel px-4 pt-[18px] md:px-6 md:pt-[22px]"
    >
      <div className="grid items-center gap-4 md:grid-cols-[1fr_360px] md:gap-8">
        <div data-testid="ledger-group-available">
          <div className="flex items-center gap-1.5 font-display text-[17px] font-semibold">
            <span id={labelId}>{t("overview.ledger.available")}</span>
            <button
              type="button"
              aria-label={hidden ? t("hidden.show") : t("hidden.hide")}
              onClick={toggle}
              className="inline-flex size-[30px] items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-gain"
            >
              <EyeIcon aria-hidden="true" className="size-[18px]" />
            </button>
            {balanceInfo !== undefined && <InfoButton disclosure={disclosure} label={balanceInfo.label} />}
          </div>
          <PoolEyebrow exchange={pool.exchange} venue={pool.venue} currency={currency} sole={sole} />
          <div className="mb-1.5 mt-3.5 flex items-baseline gap-2.5">
            <span data-testid="ledger-lead" className="flex items-baseline gap-2.5 text-[34px] font-medium leading-none tracking-[-0.01em] md:text-[42px]">
              {available === null ? (
                NO_FIGURE
              ) : (
                <>
                  <span className="font-mono">
                    <Masked>{amountText(available, currency, locale)}</Masked>
                  </span>
                  <span className="text-[17px] font-normal tracking-normal text-ink-3">{currency}</span>
                </>
              )}
            </span>
          </div>
          <p data-testid="header-capital" className="text-[13px] text-ink-3">
            {t("overview.header.capital")}{" "}
            <span className="font-mono text-ink-2">
              <Masked>{reserved === null ? NO_FIGURE : `${amountText(reserved, currency, locale)} ${currency}`}</Masked>
            </span>
          </p>
          {balanceInfo !== undefined && (
            <InfoText disclosure={disclosure}>
              <p data-testid="balance-stale" className="mt-1.5 font-mono text-[11px] text-ink-2">
                {balanceInfo.text}
              </p>
            </InfoText>
          )}
        </div>
        <div>{report === null ? status : <Spark report={report} asOf={asOf} locale={locale} />}</div>
      </div>
      {report === null ? (
        <div className="pb-[18px] md:pb-[22px]" />
      ) : (
        <Stats pool={pool} report={report} locale={locale} openCount={openCount} />
      )}
    </section>
  );
}

/** The sparkline's title row, with the 30-day return beside it, and the drawing under both. */
function Spark({ report, asOf, locale }: { report: PoolPerformance; asOf: number; locale: string }) {
  const { t } = useTranslation();
  const entry = report.ranges.find((range) => range.range === SPARK_RANGE);
  const value = entry === undefined ? null : parseDecimal(entry.return);
  return (
    <div data-testid="header-spark">
      <div className="mb-1.5 flex justify-between text-[12.5px] text-ink-3">
        <span>{t("overview.header.spark", { days: SPARK_DAYS })}</span>
        <span data-testid="header-spark-return" className={cn("font-mono", value === null ? undefined : toneClass(value))}>
          {value === null ? NO_FIGURE : percentText(value, locale)}
        </span>
      </div>
      <Sparkline curve={report.curve} origin={report.origin ?? null} asOf={asOf} days={SPARK_DAYS} />
    </div>
  );
}

/** The four figures of the whole history: the "All" range's PnL and return, the deepest drawdown and the open count. */
function Stats({ pool, report, locale, openCount }: { pool: Pool; report: PoolPerformance; locale: string; openCount: number | null }) {
  const { t } = useTranslation();
  const currency = pool.settlement_currency;
  const all = report.ranges.find((range) => range.range === "All");
  const pnl = all === undefined ? null : parseDecimal(all.pnl);
  const ret = all === undefined ? null : parseDecimal(all.return);
  const drawdown = parseDecimal(report.max_drawdown);

  if (pnl === null || ret === null || drawdown === null) {
    return (
      <p role="alert" data-testid="ledger-line" className="-mx-4 mt-[18px] border-t border-rule px-4 py-4 text-sm text-loss md:-mx-6 md:px-6">
        {t("overview.ledger.unreadable")}
      </p>
    );
  }

  return (
    <dl data-testid="ledger-line" className="-mx-4 mt-[18px] grid grid-cols-2 border-t border-rule md:-mx-6 md:mt-[22px] md:grid-cols-4">
      <Stat label={t("strategies.card.totalPnl")} testId="ledger-pnl" className="border-b border-r border-rule md:border-b-0">
        <span className={toneClass(pnl)}>
          <Masked>{amountText(pnl, currency, locale, true)}</Masked>
        </span>
        <StatUnit currency={currency} />
      </Stat>
      <Stat label={t("overview.header.return")} testId="ledger-return" className="border-b border-rule md:border-b-0 md:border-r">
        <span className={toneClass(ret)}>{percentText(ret, locale)}</span>
      </Stat>
      <Stat label={t("overview.header.drawdown")} testId="ledger-deepest" className="border-r border-rule">
        <span className="text-loss">{percentText(drawdown, locale)}</span>
      </Stat>
      <Stat label={t("overview.header.open")} testId="ledger-open" className="">
        {openCount === null ? NO_FIGURE : openCount}
      </Stat>
    </dl>
  );
}
