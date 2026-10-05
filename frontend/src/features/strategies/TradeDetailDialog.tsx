import { type KeyboardEvent, type ReactNode, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import { OperationFillsTable } from "@/features/strategies/OperationFillsTable";
import { dateTimeText, figureText } from "@/features/strategies/format";
import type { StrategyTrade } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";

const DASH = "—";
const KEY = "strategies.performance.trades";

interface TradeDetailDialogProps {
  /** The strategy the operation belongs to; the fills request needs it. */
  strategyId: string;
  /** The row the dialog was opened from: every figure comes from it, with no request. */
  trade: StrategyTrade;
  /** The strategy's pool currency; every figure is in it (rule 7). */
  currency: string;
  locale: string;
  onClose: () => void;
}

/** The table's absent figure: an em dash with its reason for a screen reader, never a zero. */
function Absent({ reason }: { reason: string }) {
  return (
    <>
      <span aria-hidden="true">{DASH}</span>
      <span className="sr-only">{reason}</span>
    </>
  );
}

function Figure({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-[10px] uppercase tracking-[0.09em] text-ink-3">{label}</dt>
      <dd className="mb-3 font-mono text-[13px] tabular-nums text-ink">{children}</dd>
    </>
  );
}

function rehearsalTagKey(fillPrice: string | null): string {
  if (fillPrice === "FIXED_ONE") return `${KEY}.rehearsalFixed`;
  if (fillPrice === "ALERT") return `${KEY}.rehearsalAlert`;
  return `${KEY}.rehearsal`;
}

/** The sentence of a rehearsal operation's kind; an unknown value reads as the general one. */
function rehearsalHintKey(fillPrice: string | null): string {
  if (fillPrice === "FIXED_ONE") return `${KEY}.detail.rehearsalFixedHint`;
  if (fillPrice === "ALERT") return `${KEY}.detail.rehearsalAlertHint`;
  return `${KEY}.detail.rehearsalHint`;
}

/**
 * One operation of the trades table, opened (decision 43, design § F). Presentational: every
 * figure is rendered from the row it was opened from, with no request, so none of them waits for
 * the fills; only the fills table below the figures asks the server, by being mounted.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it, with Escape and the
 * browser's own `cancel` event routed to the same handler, as `ArchiveDialog` does. Focus moves
 * to the Close button on open; the table that opened it takes focus back on close.
 */
export function TradeDetailDialog({ strategyId, trade, currency, locale, onClose }: TradeDetailDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    closeRef.current?.focus();
    return () => {
      if (typeof dialog.close === "function") dialog.close();
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onClose();
  };

  const handleCancelEvent = (event: SyntheticEvent<HTMLDialogElement>) => {
    event.preventDefault();
    onClose();
  };

  const pnl = parseDecimal(trade.pnl);
  const ret = trade.return === null ? null : parseDecimal(trade.return);
  const capital = trade.capital_at_open === null ? null : parseDecimal(trade.capital_at_open);
  const unreadable = t(`${KEY}.cellUnreadable`);
  const noValue = t(`${KEY}.noValue`);
  const notDerivable = t(`${KEY}.notDerivable`);
  const directionKey = `${KEY}.direction.${trade.direction}`;
  const side = trade.direction === "LONG" || trade.direction === "SHORT" ? t(directionKey) : trade.direction;
  const figure = (value: string | null) =>
    value === null ? <Absent reason={notDerivable} /> : (figureText(value) ?? unreadable);
  // A rehearsal row's PnL is drawn in neutral ink, as in the table.
  const ink = (value: number | null) => (value !== null && !trade.rehearsal ? toneClass(value) : undefined);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onCancel={handleCancelEvent}
      className="fixed inset-0 m-auto max-h-[90vh] w-full max-w-2xl flex-col rounded-lg border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80 open:flex"
    >
      <div className="flex items-start justify-between gap-4 border-b border-rule p-5">
        <h2 id={titleId} className="font-display text-base font-semibold text-ink">
          {t(`${KEY}.detail.title`, { pair: trade.pair, side })}
          {trade.rehearsal && (
            <span className="block font-sans text-[11px] font-normal text-decision">
              {t(rehearsalTagKey(trade.rehearsal_fill_price))}
            </span>
          )}
        </h2>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t(`${KEY}.detail.close`)}
        </button>
      </div>
      <div className="flex min-h-0 flex-col gap-5 overflow-y-auto p-5">
        {trade.rehearsal && <p className="text-sm text-ink-2">{t(rehearsalHintKey(trade.rehearsal_fill_price))}</p>}
        <dl>
          <Figure label={t(`${KEY}.opened`)}>{dateTimeText(trade.opened_at, locale)}</Figure>
          <Figure label={t(`${KEY}.closed`)}>{dateTimeText(trade.closed_at, locale)}</Figure>
          <Figure label={t(`${KEY}.detail.entryPrice`)}>{figure(trade.entry_price)}</Figure>
          <Figure label={t(`${KEY}.detail.exitPrice`)}>{figure(trade.exit_price)}</Figure>
          <Figure
            label={
              trade.base_currency === null
                ? t(`${KEY}.detail.sizeNoBase`)
                : t(`${KEY}.detail.size`, { base: trade.base_currency })
            }
          >
            {figure(trade.size)}
          </Figure>
          <Figure label={t(`${KEY}.detail.fees`, { currency })}>{figureText(trade.fees) ?? unreadable}</Figure>
          {trade.other_fees.length > 0 && (
            <Figure label={t(`${KEY}.detail.otherFees`)}>
              {trade.other_fees.map((fee) => (
                <span key={fee.currency} className="block">
                  {t(`${KEY}.otherFee`, { amount: figureText(fee.amount) ?? unreadable, currency: fee.currency })}
                </span>
              ))}
            </Figure>
          )}
          <Figure label={t(`${KEY}.detail.pnl`, { currency })}>
            <span className={cn(ink(pnl))}>{pnl === null ? unreadable : amountText(pnl, currency, locale, true)}</span>
            {!trade.fees_complete && (
              <span title={t(`${KEY}.feesIncompleteHint`)} className="ml-2 font-sans text-[11px] text-ink-3">
                {t(`${KEY}.feesIncomplete`)}
              </span>
            )}
          </Figure>
          <Figure label={t(`${KEY}.detail.pnlPercent`)}>
            <span className={cn(ink(ret))}>
              {trade.return === null ? <Absent reason={noValue} /> : ret === null ? unreadable : percentText(ret, locale)}
            </span>
            <span className="block font-sans text-xs text-ink-3">{t(`${KEY}.detail.returnHint`)}</span>
          </Figure>
          <Figure label={t(`${KEY}.detail.capital`, { currency })}>
            {trade.capital_at_open === null ? (
              <Absent reason={noValue} />
            ) : capital === null ? (
              unreadable
            ) : (
              amountText(capital, currency, locale)
            )}
          </Figure>
          <Figure label={t(`${KEY}.detail.operationId`)}>
            <span className="break-all">{trade.allocation_id}</span>
          </Figure>
        </dl>
        <OperationFillsTable
          strategyId={strategyId}
          allocationId={trade.allocation_id}
          baseCurrency={trade.base_currency}
          operationRehearsal={trade.rehearsal}
        />
      </div>
    </dialog>
  );
}
