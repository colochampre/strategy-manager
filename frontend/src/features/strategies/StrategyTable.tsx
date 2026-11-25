import type { ReactNode } from "react";

import { ListToolbar } from "@/features/strategies/StrategySearch";
import { cn } from "@/shared/lib/cn";
import { CountChip } from "@/shared/ui/CountChip";

/** One column of a strategy list's table. */
export interface StrategyTableColumn {
  label: ReactNode;
  /** The column ends at the end of its cell (Subs., AuM, Pool / Lev.); the others start at the start (L23). */
  end?: boolean;
  /** A figure, in the mono face with tabular numerals. */
  figure?: boolean;
}

/** What a row puts in a cell; `span` runs it across that many columns (a row's figures, when they could not be read). */
export interface StrategyTableCell {
  content: ReactNode;
  span?: number;
}

export interface StrategyTableRow {
  id: string;
  testId: string;
  cells: readonly StrategyTableCell[];
}

interface StrategyTableProps {
  columns: readonly StrategyTableColumn[];
  rows: readonly StrategyTableRow[];
  /** The id of the heading that names the table. */
  labelledBy: string;
  /** The roomy size (ex15's): larger type and wider cells, for the table that has the fewest columns. */
  roomy?: boolean;
}

/**
 * The prototype's `.tbl-w.t` (ex13, ex14) and `.tbl-w.t.l` (ex15): the boxed table of the Overview's open positions, a
 * tinted heading row of words, one line a row. On a narrow screen the box scrolls sideways, never the page.
 */
export function StrategyTable({ columns, rows, labelledBy, roomy = false }: StrategyTableProps) {
  const head = cn(
    "whitespace-nowrap border-b border-rule bg-ground py-2.5 font-medium text-ink-3 first:pl-3.5 last:pr-3",
    roomy ? "px-3 text-[12.5px]" : "px-2 text-xs",
  );
  const cell = cn(
    "whitespace-nowrap border-b border-rule-soft font-sans first:pl-3.5 last:pr-3",
    roomy ? "px-3 py-[11px] text-[13px]" : "px-2 py-2.5 text-[12.5px]",
  );

  return (
    <div className={cn("overflow-x-auto rounded-lg border border-rule", roomy ? "mx-[22px] mt-3 mb-1.5" : "mx-4 mt-3 mb-1.5")}>
      <table aria-labelledby={labelledBy} className="w-full border-collapse">
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={index} scope="col" className={cn(head, column.end ? "text-right" : "text-left")}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            let at = 0;
            return (
              <tr key={row.id} data-testid={row.testId} className="[&:last-child>td]:border-b-0">
                {row.cells.map((entry, index) => {
                  const column = columns[at];
                  at += entry.span ?? 1;
                  return (
                    <td
                      key={index}
                      colSpan={entry.span}
                      className={cn(
                        cell,
                        entry.span === undefined && column?.end ? "text-right" : "text-left",
                        entry.span === undefined && column?.figure && "font-mono tabular-nums",
                      )}
                    >
                      {entry.content}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface TableCardProps {
  title: string;
  headingId: string;
  /** The count beside the title, as the Overview's positions card writes it ("3 positions"). */
  count: string;
  countTestId: string;
  /** Under the table, in the card: the note of the archived strategies. */
  footer?: ReactNode;
  children: ReactNode;
}

/** The prototype's `.card` of a table: the title (17 px display) with its count chip, the table, and an optional note. */
export function TableCard({ title, headingId, count, countTestId, footer, children }: TableCardProps) {
  return (
    <section aria-labelledby={headingId} className="min-w-0 rounded-[10px] border border-rule bg-panel">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-[22px] pt-[18px]">
        <h2 id={headingId} className="font-display text-[17px] font-semibold text-ink">
          {title}
        </h2>
        <CountChip testId={countTestId}>{count}</CountChip>
      </div>
      {children}
      {footer === undefined ? <div className="h-2.5" /> : <div className="px-[22px] pb-4 pt-3">{footer}</div>}
    </section>
  );
}

interface ToolbarCardProps {
  search: ReactNode;
  /** The list's own buttons, at the right of the search. */
  actions?: ReactNode;
  /** The sort buttons, on a row of their own under a soft rule. */
  sort: ReactNode;
}

/** The prototype's search card: the search and the list's buttons, and the order beneath them, in one card. */
export function ToolbarCard({ search, actions, sort }: ToolbarCardProps) {
  return (
    <section className="rounded-[10px] border border-rule bg-panel px-[22px] pb-[22px] pt-[18px]">
      <ListToolbar search={search}>{actions}</ListToolbar>
      <div className="mt-3.5 border-t border-rule-soft pt-3.5">{sort}</div>
    </section>
  );
}
