import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { StrategyLink } from "@/features/discrepancies/StrategyLink";
import { baseCurrencyOf, quantityText } from "@/features/discrepancies/figures";
import { groupByExchange } from "@/features/discrepancies/groupByExchange";
import type { BookedItem } from "@/shared/api/discrepancies";
import { cn } from "@/shared/lib/cn";
import { clockText, compactDateText } from "@/shared/lib/figure-text";
import { useIsWide } from "@/shared/layout/useIsWide";

interface BookedListProps {
  items: readonly BookedItem[];
  /** The id of the heading that names the list, for the table's accessible name. */
  labelledBy: string;
}

/** Tailwind's `md`: the width at which the cards become a table, as for the open positions. */
const MD_QUERY = "(min-width: 768px)";
const CELL = "border-b border-rule-soft py-2.5 pr-3 align-top";
const HEADER = "border-b border-rule py-2 pr-3 align-bottom font-medium";
const LABEL = "text-[10px] uppercase tracking-[0.09em] text-ink-3";

type Translate = ReturnType<typeof useTranslation>["t"];

/** What every row says of a booking, written once for the table and the card. */
interface Written {
  date: string;
  time: string | null;
  quantity: string;
  by: string;
  now: string;
}

function writtenOf(item: BookedItem, locale: string, t: Translate): Written {
  const unit = baseCurrencyOf(item.symbol, item.settlement_currency);
  const quantity = quantityText(item.quantity, locale);
  return {
    date: compactDateText(item.decided_at, locale),
    time: clockText(item.decided_at),
    quantity: unit === null ? quantity : `${quantity} ${unit}`,
    by: t(item.decided_by === "owner" ? "discrepancies.by.owner" : "discrepancies.by.automatic"),
    now: t(item.discrepancy_open ? "discrepancies.now.waiting" : "discrepancies.now.agrees"),
  };
}

interface RowProps {
  item: BookedItem;
  locale: string;
}

function BookingRow({ item, locale }: RowProps) {
  const { t } = useTranslation();
  const written = writtenOf(item, locale, t);
  return (
    <tr>
      <td className={cn(CELL, "text-left")}>
        <span className="block">{written.date}</span>{" "}
        {written.time !== null && <span className="block text-ink-3">{written.time}</span>}
      </td>
      <td className={cn(CELL, "text-left text-ink")}>{item.symbol}</td>
      <td className={cn(CELL, "text-left")}>{item.side}</td>
      <td className={cn(CELL, "text-right")}>{written.quantity}</td>
      <td className={cn(CELL, "text-left font-sans")}>
        <StrategyLink id={item.strategy_id} name={item.strategy_name} />
      </td>
      <td className={cn(CELL, "text-right")}>{item.fill_count}</td>
      <td className={cn(CELL, "text-left font-sans")}>{written.by}</td>
      <td className={cn(CELL, "text-left font-sans", item.discrepancy_open && "text-ink-3")}>{written.now}</td>
    </tr>
  );
}

/** The table: one row group per exchange so that the columns line up. */
function BookedTable({ items, labelledBy }: BookedListProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";

  return (
    <div className="overflow-x-auto">
      <table aria-labelledby={labelledBy} className="w-full border-collapse font-mono text-[13px] tabular-nums text-ink-2">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.09em] text-ink-3">
            <th scope="col" className={cn(HEADER, "text-left")}>
              {t("discrepancies.table.booked")}
            </th>
            <th scope="col" className={cn(HEADER, "text-left")}>
              {t("discrepancies.table.pair")}
            </th>
            <th scope="col" className={cn(HEADER, "text-left")}>
              {t("discrepancies.table.side")}
            </th>
            <th scope="col" className={cn(HEADER, "text-right")}>
              {t("discrepancies.table.quantity")}
            </th>
            <th scope="col" className={cn(HEADER, "text-left")}>
              {t("discrepancies.table.strategy")}
            </th>
            <th scope="col" className={cn(HEADER, "text-right")}>
              {t("discrepancies.table.fills")}
            </th>
            <th scope="col" className={cn(HEADER, "text-left")}>
              {t("discrepancies.table.by")}
            </th>
            <th scope="col" className={cn(HEADER, "pr-0 text-left")}>
              {t("discrepancies.table.now")}
            </th>
          </tr>
        </thead>
        {groupByExchange(items).map((group) => (
          <tbody key={group.exchange}>
            <tr>
              <th
                colSpan={8}
                scope="rowgroup"
                className="pb-1 pt-4 text-left font-mono text-[11px] font-medium uppercase tracking-[0.09em] text-ink-3"
              >
                {group.exchange.toUpperCase()}
              </th>
            </tr>
            {group.items.map((item) => (
              <BookingRow key={item.proposal_id} item={item} locale={locale} />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

interface CardValueProps {
  label: string;
  /** The value takes the whole row of the card. */
  full?: boolean;
  /** The value is prose (a name, a sentence), not a figure. */
  prose?: boolean;
  children: ReactNode;
}

function CardValue({ label, full = false, prose = false, children }: CardValueProps) {
  return (
    <div className={cn(full && "col-span-2")}>
      <dt className={LABEL}>{label}</dt>
      <dd className={cn("text-ink-2", prose && "font-sans")}>{children}</dd>
    </div>
  );
}

/** One card of the phone layout: the pair and side, how it was booked at the head, the values in two columns. */
function BookingCard({ item, locale }: RowProps) {
  const { t } = useTranslation();
  const written = writtenOf(item, locale, t);
  const booked = written.time === null ? written.date : `${written.date} ${written.time}`;

  return (
    <article
      aria-label={`${item.symbol} ${item.side}`}
      className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-rule bg-panel p-3.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="font-display text-base font-semibold text-ink">
          {item.symbol}
          <span className="ml-1.5 font-mono text-xs font-normal text-ink-2">{item.side}</span>
        </span>
        <span className="font-sans text-[11px] text-ink-2">{written.by}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs tabular-nums">
        <CardValue label={t("discrepancies.table.booked")}>{booked}</CardValue>
        <CardValue label={t("discrepancies.table.quantity")}>{written.quantity}</CardValue>
        <CardValue label={t("discrepancies.table.strategy")} full prose>
          <StrategyLink id={item.strategy_id} name={item.strategy_name} />
        </CardValue>
        <CardValue label={t("discrepancies.table.fills")}>{item.fill_count}</CardValue>
        <CardValue label={t("discrepancies.table.now")} prose>
          {written.now}
        </CardValue>
      </dl>
    </article>
  );
}

/**
 * The bookings of the last 30 days (owner decision 66, Q5): a table with one row group per exchange from `md`
 * upward and one card per booking below it. It renders ONE of the two, never both hidden by CSS, so the links
 * and the accessible names exist once. A booking is a result, never red.
 */
export function BookedList({ items, labelledBy }: BookedListProps) {
  const { i18n } = useTranslation();
  const table = useIsWide(MD_QUERY);
  const locale = i18n.resolvedLanguage ?? "en";
  if (table) return <BookedTable items={items} labelledBy={labelledBy} />;

  return (
    <>
      {groupByExchange(items).map((group) => (
        <ExchangeCards key={group.exchange} exchange={group.exchange}>
          {group.items.map((item) => (
            <BookingCard key={item.proposal_id} item={item} locale={locale} />
          ))}
        </ExchangeCards>
      ))}
    </>
  );
}

interface ExchangeCardsProps {
  exchange: string;
  children: ReactNode;
}

function ExchangeCards({ exchange, children }: ExchangeCardsProps) {
  return (
    <section aria-label={exchange} className="flex min-w-0 flex-col gap-2">
      <h3 className="font-mono text-sm font-medium text-ink-2">{exchange}</h3>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}
