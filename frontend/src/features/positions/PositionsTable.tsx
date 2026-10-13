import { Fragment } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { VenueLine } from "@/features/positions/MarkLine";
import { OriginTag } from "@/features/positions/OriginTag";
import type { OpenPosition } from "@/shared/api/positions";
import { amountText, parseDecimal } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { figureText, tableFigureText } from "@/shared/lib/figure-text";
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
function cellsOf(position: OpenPosition, locale: string, t: Translate): ReactNode[] {
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
    position.opened_at === null ? <Absent reason={unreadable} /> : <Instant iso={position.opened_at} locale={locale} />,
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

/** The table of a strategy's open positions, from `md` upward (design addendum § H). */
export function PositionsTable({ positions, asOf, currency, labelledBy }: PositionsTableProps) {
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
