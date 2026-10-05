import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import { TradeDetailDialog } from "@/features/strategies/TradeDetailDialog";
import { dateTimeText, figureText } from "@/features/strategies/format";
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
  /** Opens this operation; the button is handed over so focus can return to it on close. */
  onOpen: (trade: StrategyTrade, opener: HTMLButtonElement) => void;
}

const PAGER_BUTTON =
  "min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50";
const CELL = "border-b border-rule-soft py-2.5 pr-3";

// The width tiers of design § F. Each is a Tailwind viewport variant on the th AND the td, and
// the same literal strings so the compiler sees them: a column a tier hides is in the detail view.
const FROM_MD = "hidden md:table-cell";
const FROM_XL = "hidden xl:table-cell";
const FROM_WIDE = "hidden min-[90rem]:table-cell";

/**
 * The tag of a rehearsal row by its `rehearsal_fill_price`. `UNDETERMINED`, and a value this panel
 * does not know, read as the plain tag: nothing is claimed about a price stored data cannot support.
 */
function rehearsalTagKey(fillPrice: string | null): string {
  if (fillPrice === "FIXED_ONE") return "strategies.performance.trades.rehearsalFixed";
  if (fillPrice === "ALERT") return "strategies.performance.trades.rehearsalAlert";
  return "strategies.performance.trades.rehearsal";
}

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

function TradeRow({ trade, currency, locale, onOpen }: TradeRowProps) {
  const { t } = useTranslation();
  const pnl = parseDecimal(trade.pnl);
  const ret = trade.return === null ? null : parseDecimal(trade.return);
  const capital = trade.capital_at_open === null ? null : parseDecimal(trade.capital_at_open);
  const unreadable = t("strategies.performance.trades.cellUnreadable");
  const noValue = t("strategies.performance.trades.noValue");
  const notDerivable = t("strategies.performance.trades.notDerivable");
  const directionKey = `strategies.performance.trades.direction.${trade.direction}`;
  const side = trade.direction === "LONG" || trade.direction === "SHORT" ? t(directionKey) : trade.direction;
  // A null entry, exit or size is "not derivable from the fills", never a zero; a string that is
  // not a number is unreadable, never drawn as typed.
  const figure = (value: string | null) =>
    value === null ? <Absent reason={notDerivable} /> : (figureText(value) ?? unreadable);

  return (
    <tr>
      <td className={cn(CELL, "text-left", FROM_WIDE)}>{dateTimeText(trade.opened_at, locale)}</td>
      <td className={cn(CELL, "text-left")}>{dateTimeText(trade.closed_at, locale)}</td>
      <td className={cn(CELL, "text-left text-ink")}>
        {trade.pair}
        {trade.rehearsal && (
          <span className="block font-sans text-[11px] text-decision">
            {t(rehearsalTagKey(trade.rehearsal_fill_price))}
          </span>
        )}
      </td>
      <td className={cn(CELL, "text-left")}>{side}</td>
      <td className={cn(CELL, FROM_MD)}>{figure(trade.entry_price)}</td>
      <td className={cn(CELL, FROM_MD)}>{figure(trade.exit_price)}</td>
      <td className={cn(CELL, FROM_XL)}>{figure(trade.size)}</td>
      <td className={cn(CELL, FROM_XL)}>
        {figureText(trade.fees) ?? unreadable}
        {trade.other_fees.map((fee) => (
          <span key={fee.currency} className="ml-2 font-sans text-[11px] text-ink-3">
            {t("strategies.performance.trades.otherFee", {
              amount: figureText(fee.amount) ?? unreadable,
              currency: fee.currency,
            })}
          </span>
        ))}
      </td>
      <td className={cn(CELL, pnl !== null && !trade.rehearsal && toneClass(pnl))}>
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
      <td className={cn(CELL, ret !== null && !trade.rehearsal && toneClass(ret))}>
        {trade.return === null ? <Absent reason={noValue} /> : ret === null ? unreadable : percentText(ret, locale)}
      </td>
      <td className={cn(CELL, FROM_XL)}>
        {trade.capital_at_open === null ? (
          <Absent reason={noValue} />
        ) : capital === null ? (
          unreadable
        ) : (
          amountText(capital, currency, locale)
        )}
      </td>
      <td className="border-b border-rule-soft py-2.5">
        <button
          type="button"
          onClick={(event) => onOpen(trade, event.currentTarget)}
          aria-label={t("strategies.performance.trades.detailsOf", {
            pair: trade.pair,
            side,
            closed: dateTimeText(trade.closed_at, locale),
          })}
          className="min-h-11 rounded-md border border-rule px-3 font-sans text-xs text-ink hover:bg-panel-2"
        >
          {t("strategies.performance.trades.details")}
        </button>
      </td>
    </tr>
  );
}

/**
 * The strategy's closed trades, newest first, ONE page of 20 on screen at a
 * time. Paging is the server's keyset cursor (`useStrategyTrades`), never an
 * offset: "Next" asks for the page after the last one served, with the exact
 * cursor, only when that page is not loaded yet; "Previous" reads the pages
 * already loaded and sends nothing. There is no page count, because the
 * server serves no total; Next ends where the server answers no cursor. A
 * failed next page leaves the current page on screen and says so; the same
 * button asks again.
 *
 * It shows what `GET /performance/strategies/{id}/trades` serves: twelve columns,
 * of which the narrower viewports show the first tiers of design § F and leave
 * the rest to the detail view (decision 43).
 */
export function TradesTable(props: TradesTableProps) {
  // Keyed by strategy: another strategy's list starts on its first page.
  return <TradesTableView key={props.strategyId} {...props} />;
}

function TradesTableView({ strategyId, currency }: TradesTableProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const locale = i18n.resolvedLanguage ?? "en";
  const trades = useStrategyTrades(strategyId);
  // The page on screen, an index into the pages loaded so far. Previous only moves it; Next moves it too,
  // and asks the server first when that page is not loaded yet.
  const [pageIndex, setPageIndex] = useState(0);
  // The one operation opened, if any, and the button that opened it: the figures come from the row,
  // the fills are asked for by the dialog being mounted. Opening another replaces it.
  const [open, setOpen] = useState<StrategyTrade | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const openOperation = (trade: StrategyTrade, button: HTMLButtonElement) => {
    opener.current = button;
    setOpen(trade);
  };
  // Once the dialog is gone, focus goes back to the Details button that opened it.
  useEffect(() => {
    if (open === null) opener.current?.focus();
  }, [open]);

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
    const pages = trades.data.pages;
    const rows = (pages[pageIndex] ?? pages[0])?.trades ?? [];
    const loadedAhead = pageIndex + 1 < pages.length;
    const canGoNext = loadedAhead || trades.hasNextPage;
    const goNext = async () => {
      if (loadedAhead) {
        setPageIndex(pageIndex + 1);
        return;
      }
      const result = await trades.fetchNextPage();
      // A failed read leaves this page on screen; `isFetchNextPageError` says so and the same button asks again.
      if (!result.isError) setPageIndex(pageIndex + 1);
    };
    if (rows.length === 0 && pageIndex === 0) {
      body = <p className="text-sm text-ink-3">{t("strategies.performance.trades.empty")}</p>;
    } else {
      const header = "border-b border-rule py-2 pr-3 font-medium";
      // Each sentence is true of a row of the page on screen: `rows` is that one page, never the
      // pages visited before, so a sentence goes when the page that made it true is left.
      const notes = [
        rows.some((row) => row.rehearsal) && "rehearsalNote",
        rows.some((row) => row.rehearsal && row.rehearsal_fill_price === "FIXED_ONE") && "rehearsalFixedNote",
        rows.some((row) => row.rehearsal && row.rehearsal_fill_price === "ALERT") && "rehearsalAlertNote",
      ].filter((key): key is string => key !== false);
      body = (
        <>
          {notes.map((key) => (
            <p key={key} className="text-sm text-ink-2">
              {t(`strategies.performance.trades.${key}`)}
            </p>
          ))}
          <div className="overflow-x-auto">
            <table aria-labelledby={headingId} className="w-full border-collapse font-mono text-[13px] tabular-nums">
              <thead>
                <tr className="text-right text-[10px] uppercase tracking-[0.09em] text-ink-3">
                  <th scope="col" className={cn(header, "text-left", FROM_WIDE)}>
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
                  <th scope="col" className={cn(header, FROM_MD)}>
                    {t("strategies.performance.trades.entry")}
                  </th>
                  <th scope="col" className={cn(header, FROM_MD)}>
                    {t("strategies.performance.trades.exit")}
                  </th>
                  <th scope="col" className={cn(header, FROM_XL)}>
                    {t("strategies.performance.trades.size")}
                  </th>
                  <th scope="col" className={cn(header, FROM_XL)}>
                    {t("strategies.performance.trades.fees", { currency })}
                  </th>
                  <th scope="col" className={header}>
                    {t("strategies.performance.trades.pnl", { currency })}
                  </th>
                  <th scope="col" className={header}>
                    {t("strategies.performance.trades.return")}
                  </th>
                  <th scope="col" className={cn(header, FROM_XL)}>
                    {t("strategies.performance.trades.capital")}
                  </th>
                  <th scope="col" className="border-b border-rule py-2 font-medium">
                    {t("strategies.performance.trades.details")}
                  </th>
                </tr>
              </thead>
              <tbody className="text-right text-ink-2">
                {rows.map((trade) => (
                  <TradeRow
                    key={trade.allocation_id}
                    trade={trade}
                    currency={currency}
                    locale={locale}
                    onOpen={openOperation}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {trades.isFetchNextPageError && (
            <p role="alert" className="text-sm text-loss">
              {t("strategies.performance.trades.nextFailed")}
            </p>
          )}
          <nav aria-label={t("strategies.performance.trades.pagination")} className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={pageIndex === 0}
              onClick={() => setPageIndex(pageIndex - 1)}
              className={PAGER_BUTTON}
            >
              {t("strategies.performance.trades.previous")}
            </button>
            <span className="font-mono text-xs text-ink-2">
              {t("strategies.performance.trades.page", { page: pageIndex + 1 })}
            </span>
            <button
              type="button"
              disabled={!canGoNext || trades.isFetchingNextPage}
              onClick={() => void goNext()}
              className={PAGER_BUTTON}
            >
              {t(trades.isFetchingNextPage ? "strategies.performance.trades.loadingMore" : "strategies.performance.trades.next")}
            </button>
          </nav>
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
      {open !== null && (
        <TradeDetailDialog
          key={open.allocation_id}
          strategyId={strategyId}
          trade={open}
          currency={currency}
          locale={locale}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}
