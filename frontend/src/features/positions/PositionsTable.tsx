import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { OriginTag } from "@/features/positions/OriginTag";
import type { OpenPosition } from "@/shared/api/positions";
import { cn } from "@/shared/lib/cn";
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

/** The eight cells of a position, in the order of the columns. A null is never passed on to a formatter. */
function cellsOf(position: OpenPosition, locale: string, t: Translate): ReactNode[] {
  const unreadable = reasonOf(position, t, "other");
  const nullable = (value: string | null, write: (value: string) => ReactNode): ReactNode =>
    value === null ? <Absent reason={unreadable} /> : write(value);

  return [
    position.opened_at === null ? <Absent reason={unreadable} /> : <Instant iso={position.opened_at} locale={locale} />,
    <>
      {position.markets.join(" / ")}
      <span className="block font-sans text-[11px] leading-4">
        <OriginTag origin={position.origin} />
      </span>
    </>,
    position.side === null ? <Absent reason={unreadable} /> : t(`strategies.performance.trades.direction.${position.side}`),
    nullable(position.size, (size) => size),
    nullable(position.entry_price, (price) => price),
    nullable(position.fees, (fees) => fees),
    nullable(position.margin_granted, (margin) => margin),
    position.leverage === null ? (
      <Absent reason={reasonOf(position, t, "leverage")} />
    ) : (
      t("positions.table.leverageValue", { value: position.leverage })
    ),
  ];
}

/** The table of a strategy's open positions, from `md` upward (design addendum § H). */
export function PositionsTable({ positions, currency, labelledBy }: PositionsTableProps) {
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
              <tr key={position.allocation_id}>
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
