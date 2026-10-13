import { Fragment } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { VenueLine } from "@/features/positions/MarkLine";
import { OriginTag } from "@/features/positions/OriginTag";
import type { OpenPosition } from "@/shared/api/positions";
import { amountText, parseDecimal } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { clockText, compactDateText, figureText, tableFigureText } from "@/shared/lib/figure-text";
import { useIsWide } from "@/shared/layout/useIsWide";
import { Absent } from "@/shared/ui/Absent";
import { Instant } from "@/shared/ui/Instant";

interface PositionsTableProps {
  positions: OpenPosition[];
  /** The answer's `as_of`. */
  asOf: string;
  /** The pool's settlement currency, written in the Fees and Margin headings. */
  currency: string;
  /** The id of the heading that names the table. */
  labelledBy: string;
  variant: "strategy";
}

type Translate = ReturnType<typeof useTranslation>["t"];

const CELL = "border-b border-rule-soft py-2.5 pr-3 align-top";
const HEADER = "border-b border-rule py-2 pr-3 align-bottom font-medium";

/**
 * A position the facts could not decorate has no figure at all: every empty cell says so. A position that has
 * its facts and no leverage was simply not recorded, which is the one case "not recorded" is true of.
 */
function reasonOf(position: OpenPosition, t: Translate, column: "leverage" | "other"): string {
  if (column === "leverage" && position.figures_missing !== "NO_FACTS") return t("positions.table.notRecorded");
  return t("positions.state.unreadable");
}

const ASIDE = "block font-sans text-[11px] text-ink-3";

/**
 * The eight cells of a position, in the order of the columns. A null is never passed on to a formatter, and a
 * stored figure is written, never recomputed: the helpers of the closed trades table, which sits right under
 * this section, so that one page writes a figure one way (prices and sizes by `tableFigureText`, fees and
 * margin by `amountText` in the currency's decimals, the leverage by `figureText` and an `x`).
 */
function cellsOf(position: OpenPosition, locale: string, t: Translate, inlineOpened = false): ReactNode[] {
  const unreadable = reasonOf(position, t, "other");
  const unreadableFigure = t("positions.state.unreadable");
  const nullable = (value: string | null, write: (value: string) => ReactNode): ReactNode =>
    value === null ? <Absent reason={unreadable} /> : write(value);
  const money = (amount: string): string => {
    const parsed = parseDecimal(amount);
    return parsed === null ? unreadableFigure : amountText(parsed, position.currency, locale);
  };
  const opened = position.opened_size === null ? null : tableFigureText(position.opened_size);
  const held = position.size === null ? null : tableFigureText(position.size);

  return [
    position.opened_at === null ? (
      <Absent reason={unreadable} />
    ) : inlineOpened ? (
      // A card has room for the date and the time on one line (example 20).
      [compactDateText(position.opened_at, locale), clockText(position.opened_at)].filter((part) => part !== null).join(" ")
    ) : (
      <Instant iso={position.opened_at} locale={locale} />
    ),
    <>
      {position.markets.join(" / ")}
      <span className="block font-sans text-[11px] leading-4">
        <OriginTag origin={position.origin} />
      </span>
    </>,
    position.side === null ? <Absent reason={unreadable} /> : t(`strategies.performance.trades.direction.${position.side}`),
    nullable(position.size, () => (
      <>
        {held ?? unreadableFigure}
        {position.base_currency !== null && (
          <>
            {" "}
            <span className="font-sans text-[11px] text-ink-3">{position.base_currency}</span>
          </>
        )}
        {opened !== null && opened !== held && <span className={ASIDE}>{t("positions.table.ofOpened", { opened })}</span>}
      </>
    )),
    nullable(position.entry_price, (price) => (
      <>
        {tableFigureText(price) ?? unreadableFigure}
        {position.fill_count > 1 && <span className={ASIDE}>{t("positions.table.averageOf", { fills: position.fill_count })}</span>}
      </>
    )),
    nullable(position.fees, (fees) => (
      <>
        {money(fees)}
        {position.other_fees.map((fee) => (
          <span key={fee.currency} className="ml-2 font-sans text-[11px] text-ink-3">
            {t("strategies.performance.trades.otherFee", {
              amount: figureText(fee.amount) ?? unreadableFigure,
              currency: fee.currency,
            })}
          </span>
        ))}
      </>
    )),
    nullable(position.margin_granted, money),
    position.leverage === null ? (
      <Absent reason={reasonOf(position, t, "leverage")} />
    ) : (
      t("positions.table.leverageValue", { value: figureText(position.leverage) ?? unreadableFigure })
    ),
  ];
}

const COLUMNS = 8;
/** Tailwind's `md`: the width at which the cards become a table. */
const MD_QUERY = "(min-width: 768px)";
/** A sub-row is a real row with one cell across the table; it is never a flex wrapper (it would collapse into the first column). */
const SUB_CELL = "border-b border-rule-soft pb-2.5 pt-1.5 text-left";
const SUB_TEXT = "font-sans text-xs text-ink-2";

interface SubRow {
  key: string;
  content: ReactNode;
}

/** The reason a position's figures are missing: its own text for the three codes the server names, the generic one for any other. */
function reasonText(code: string, t: Translate): string {
  return t(code === "UNRESOLVED_SYMBOL" || code === "SEVERAL_MARKETS" || code === "FLIPPED" ? `positions.reason.${code}` : "positions.reason.other");
}

/**
 * What goes under a position's row, in this order: the venue line, the reason its figures are missing, and the
 * reservation's note when its status is not FILLED. A position the venue disagrees on is a red line, and an
 * unresolved or unreserved one says so: none of them reads as a clean row (design § K rows 2, 4, 14, 22).
 */
export function subRowsOf(position: OpenPosition, asOf: string, t: Translate): SubRow[] {
  const rows: SubRow[] = [];
  if (position.venue_disagreement !== null) {
    rows.push({ key: "venue", content: <VenueLine position={position} asOf={asOf} /> });
  }
  if (position.figures_missing !== null) {
    rows.push({ key: "reason", content: <p className={SUB_TEXT}>{reasonText(position.figures_missing, t)}</p> });
  }
  if (position.reservation_status !== null && position.reservation_status !== "FILLED") {
    rows.push({
      key: "reservation",
      content: <p className={SUB_TEXT}>{t("positions.note.reservation", { status: position.reservation_status })}</p>,
    });
  }
  return rows;
}

type TableProps = Omit<PositionsTableProps, "variant">;

/** The table, from `md` upward (design addendum § H). */
function DesktopTable({ positions, asOf, currency, labelledBy }: TableProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const left = "text-left";

  return (
    <div className="overflow-x-auto">
      <table aria-labelledby={labelledBy} className="w-full border-collapse font-mono text-[13px] tabular-nums">
        <thead>
          <tr className="text-right text-[10px] uppercase tracking-[0.09em] text-ink-3">
            <th scope="col" className={cn(HEADER, left)}>
              {t("strategies.performance.trades.opened")}
            </th>
            <th scope="col" className={cn(HEADER, left)}>
              {t("strategies.performance.trades.pair")}
            </th>
            <th scope="col" className={cn(HEADER, left)}>
              {t("strategies.performance.trades.side")}
            </th>
            <th scope="col" className={HEADER}>
              {t("strategies.performance.trades.size")}
            </th>
            <th scope="col" className={HEADER}>
              {t("strategies.performance.trades.entry")}
            </th>
            <th scope="col" className={HEADER}>
              {t("strategies.performance.trades.fees", { currency })}
            </th>
            <th scope="col" className={HEADER}>
              {t("positions.table.margin", { currency })}
            </th>
            <th scope="col" className="border-b border-rule py-2 align-bottom font-medium">
              {t("positions.table.leverage")}
            </th>
          </tr>
        </thead>
        <tbody className="text-right text-ink-2">
          {positions.map((position) => {
            const cells = cellsOf(position, locale, t);
            return (
              <Fragment key={position.allocation_id}>
                <tr>
                  {cells.map((cell, index) => (
                    <td
                      key={index}
                      className={cn(
                        CELL,
                        index < 3 && "text-left",
                        index === 1 && "text-ink",
                        index === cells.length - 1 && "pr-0",
                      )}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
                {subRowsOf(position, asOf, t).map((sub) => (
                  <tr key={sub.key}>
                    <td colSpan={COLUMNS} className={SUB_CELL}>
                      {sub.content}
                    </td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const LABEL = "text-[10px] uppercase tracking-[0.09em] text-ink-3";

/** One card of the phone layout: the pair and the side in the head, the origin's word at its right, the six labelled values in two columns, then the sub-rows. */
function PositionCard({ position, asOf, currency, locale }: { position: OpenPosition; asOf: string; currency: string; locale: string }) {
  const { t } = useTranslation();
  const cells = cellsOf(position, locale, t, true);
  const pair = position.markets.join(" / ");
  const side = position.side === null ? t("positions.sideUnreadable") : position.side;
  const labelled: ReadonlyArray<readonly [string, ReactNode]> = [
    [t("strategies.performance.trades.opened"), cells[0]],
    [t("strategies.performance.trades.size"), cells[3]],
    [t("strategies.performance.trades.entry"), cells[4]],
    [t("strategies.performance.trades.fees", { currency }), cells[5]],
    [t("positions.table.margin", { currency }), cells[6]],
    [t("positions.table.leverage"), cells[7]],
  ];

  return (
    <article
      aria-label={`${pair} ${side}`}
      className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-rule bg-panel p-3.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 font-sans text-[11px] leading-4">
        <span className="font-display text-base font-semibold text-ink">
          {pair}
          <span className="ml-1.5 font-mono text-xs font-normal text-ink-2">{cells[2]}</span>
        </span>
        <OriginTag origin={position.origin} />
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs tabular-nums">
        {labelled.map(([label, value]) => (
          <div key={label}>
            <dt className={LABEL}>{label}</dt>
            <dd className="text-ink-2">{value}</dd>
          </div>
        ))}
      </dl>
      {subRowsOf(position, asOf, t).map((sub) => (
        <div key={sub.key}>{sub.content}</div>
      ))}
    </article>
  );
}

/**
 * The open positions of a strategy: a table from `md` upward and, below it, one card per position (the
 * prototype's example 20 decides, N2). It renders ONE of the two, never both hidden by CSS, so that the venue
 * line, the links and the accessible names exist once.
 */
export function PositionsTable({ variant: _variant, ...props }: PositionsTableProps) {
  const { i18n } = useTranslation();
  const table = useIsWide(MD_QUERY);
  if (table) return <DesktopTable {...props} />;
  const locale = i18n.resolvedLanguage ?? "en";
  return (
    <div className="flex flex-col gap-3">
      {props.positions.map((position) => (
        <PositionCard key={position.allocation_id} position={position} asOf={props.asOf} currency={props.currency} locale={locale} />
      ))}
    </div>
  );
}
