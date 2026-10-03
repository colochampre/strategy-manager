import { useId } from "react";
import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import { dateTimeText } from "@/features/strategies/format";
import { useStrategyTrades } from "@/shared/api/performance";
import type { StrategyTrade } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";

const DASH = "—";

interface TradesTableProps {
  strategyId: string;
  /** The strategy's pool currency; every figure is in it (rule 7). */
  currency: string;
}

interface TradeRowProps {
  trade: StrategyTrade;
  currency: string;
  locale: string;
}

const CELL = "border-b border-rule-soft py-2.5 pr-3";

/**
 * A figure that is absent (null) is an em dash with its reason for a screen
 * reader; one that is present but cannot be read says so. Neither is a zero.
 */
function Absent({ reason }: { reason: string }) {
  return (
    <>
      <span aria-hidden="true">{DASH}</span>
      <span className="sr-only">{reason}</span>
    </>
  );
}

function TradeRow({ trade, currency, locale }: TradeRowProps) {
  const { t } = useTranslation();
  const pnl = parseDecimal(trade.pnl);
  const ret = trade.return === null ? null : parseDecimal(trade.return);
  const capital = trade.capital_at_open === null ? null : parseDecimal(trade.capital_at_open);
  const unreadable = t("strategies.performance.trades.cellUnreadable");
  const noValue = t("strategies.performance.trades.noValue");
  const directionKey = `strategies.performance.trades.direction.${trade.direction}`;

  return (
    <tr>
      <td className={cn(CELL, "text-left")}>{dateTimeText(trade.opened_at, locale)}</td>
      <td className={cn(CELL, "text-left")}>{dateTimeText(trade.closed_at, locale)}</td>
      <td className={cn(CELL, "text-left text-ink")}>{trade.pair}</td>
      <td className={cn(CELL, "text-left")}>{trade.direction === "LONG" || trade.direction === "SHORT" ? t(directionKey) : trade.direction}</td>
      <td className={cn(CELL, pnl !== null && toneClass(pnl))}>
        {pnl === null ? unreadable : amountText(pnl, currency, locale, true)}
        {!trade.fees_complete && (
          <span
            title={t("strategies.performance.trades.feesIncompleteHint")}
            className="ml-2 font-sans text-[11px] text-ink-3"
          >
            {t("strategies.performance.trades.feesIncomplete")}
          </span>
        )}
      </td>
      <td className={cn(CELL, ret !== null && toneClass(ret))}>
        {trade.return === null ? <Absent reason={noValue} /> : ret === null ? unreadable : percentText(ret, locale)}
      </td>
      <td className="border-b border-rule-soft py-2.5">
        {trade.capital_at_open === null ? (
          <Absent reason={noValue} />
        ) : capital === null ? (
          unreadable
        ) : (
          amountText(capital, currency, locale)
        )}
      </td>
    </tr>
  );
}

/**
 * The strategy's closed trades, newest first, a page at a time. Paging is the
 * server's keyset cursor (`useStrategyTrades`), never an offset: "Load more"
 * asks for the page after the last one served, and the list ends when the
 * server answers no cursor. A failed next page leaves every row already
 * loaded in place and says so; the same button asks again.
 *
 * It shows what `GET /performance/strategies/{id}/trades` serves. Entry and
 * exit price, size and fees paid are decision 43 and are not served yet.
 */
export function TradesTable({ strategyId, currency }: TradesTableProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const locale = i18n.resolvedLanguage ?? "en";
  const trades = useStrategyTrades(strategyId);

  let body;
  if (trades.data === undefined && trades.status === "error") {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p role="alert" className="text-sm text-loss">
          {t("strategies.performance.trades.error")}
        </p>
        <button
          type="button"
          onClick={() => void trades.refetch()}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("strategies.performance.trades.retry")}
        </button>
      </div>
    );
  } else if (trades.data === undefined) {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.performance.trades.loading")}
      </p>
    );
  } else {
    const rows = trades.data.pages.flatMap((page) => page.trades);
    if (rows.length === 0) {
      body = <p className="text-sm text-ink-3">{t("strategies.performance.trades.empty")}</p>;
    } else {
      const header = "border-b border-rule py-2 pr-3 font-medium";
      body = (
        <>
          <div className="overflow-x-auto">
            <table aria-labelledby={headingId} className="w-full border-collapse font-mono text-[13px] tabular-nums">
              <thead>
                <tr className="text-right text-[10px] uppercase tracking-[0.09em] text-ink-3">
                  <th scope="col" className={cn(header, "text-left")}>
                    {t("strategies.performance.trades.opened")}
                  </th>
                  <th scope="col" className={cn(header, "text-left")}>
                    {t("strategies.performance.trades.closed")}
                  </th>
                  <th scope="col" className={cn(header, "text-left")}>
                    {t("strategies.performance.trades.pair")}
                  </th>
                  <th scope="col" className={cn(header, "text-left")}>
                    {t("strategies.performance.trades.side")}
                  </th>
                  <th scope="col" className={header}>
                    {t("strategies.performance.trades.pnl", { currency })}
                  </th>
                  <th scope="col" className={header}>
                    {t("strategies.performance.trades.return")}
                  </th>
                  <th scope="col" className="border-b border-rule py-2 font-medium">
                    {t("strategies.performance.trades.capital")}
                  </th>
                </tr>
              </thead>
              <tbody className="text-right text-ink-2">
                {rows.map((trade) => (
                  <TradeRow key={trade.allocation_id} trade={trade} currency={currency} locale={locale} />
                ))}
              </tbody>
            </table>
          </div>
          {trades.isFetchNextPageError && (
            <p role="alert" className="text-sm text-loss">
              {t("strategies.performance.trades.nextFailed")}
            </p>
          )}
          {trades.hasNextPage && (
            <button
              type="button"
              disabled={trades.isFetchingNextPage}
              onClick={() => void trades.fetchNextPage()}
              className="min-h-11 self-start rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
            >
              {t(trades.isFetchingNextPage ? "strategies.performance.trades.loadingMore" : "strategies.performance.trades.loadMore")}
            </button>
          )}
        </>
      );
    }
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("strategies.performance.trades.title")}
      </h2>
      {body}
    </section>
  );
}
