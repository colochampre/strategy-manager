import type { ReactNode } from "react";

import { cn } from "@/shared/lib/cn";

/**
 * A strategy's first card, drawn as the dashboard's header card (ex1): the description at the top, where the
 * dashboard has the available balance, and the row of figures under it (S14, ex11 and ex12). The card's own frame
 * is the dashboard's; the figures arrive as `children`, a `StatsRow`.
 */
export function StrategyHeaderCard({ about, children }: { about: ReactNode; children: ReactNode }) {
  return (
    <section
      data-testid="strategy-header-card"
      className="rounded-[10px] border border-rule bg-panel px-4 pt-[18px] md:px-6 md:pt-[22px]"
    >
      {about}
      {children}
    </section>
  );
}

/** How many figures a row holds: four, or five where the PnL and the return are two (L42). */
export type RowCount = 4 | 5;

/**
 * The row's figures, two a row on a phone and all of them from `md`, a rule over it and out to the card's edges. From
 * `md` each column is as wide as its figure needs and the room left is shared out, so a long AuM takes it from a
 * short return instead of spilling out of an equal fifth (L42).
 */
export function StatsRow({ testId, count = 4, children }: { testId: string; count?: RowCount; children: ReactNode }) {
  return (
    <dl
      data-testid={testId}
      className={cn(
        "-mx-4 mt-[18px] grid min-w-0 grid-cols-2 border-t border-rule md:-mx-6 md:mt-[22px]",
        count === 5 ? "md:grid-cols-[repeat(5,auto)]" : "md:grid-cols-[repeat(4,auto)]",
      )}
    >
      {children}
    </dl>
  );
}

/**
 * Where the rules between figures fall, by the figure's place in the row: two a row on a phone, all in one row from
 * `md`, as the dashboard's header card rules them. The first is set in from the card's edge by the card's own padding.
 * An odd last figure takes a phone's whole row.
 */
function tileRules(position: number, count: RowCount): string {
  const last = position === count - 1;
  const alone = last && count % 2 === 1;
  const lastPhoneRow = Math.floor(position / 2) === Math.floor((count - 1) / 2);
  return cn(
    position % 2 === 0 && !alone && "border-r border-rule",
    !lastPhoneRow && "border-b border-rule md:border-b-0",
    !last && position % 2 === 1 && "border-rule md:border-r",
    position === 0 && "md:pl-6",
    alone && "col-span-2 md:col-span-1",
  );
}

interface StatTileProps {
  testId: string;
  label: string;
  /** The (i) after the label, for a figure that has one. */
  info?: ReactNode;
  /** The figure's place in the row, from 0. */
  position: number;
  /** How many figures the row holds, the rules depend on it. */
  count?: RowCount;
  /** The lead figure, then its quiet part beside it, if it has one. */
  children: ReactNode;
}

/**
 * One figure of the row: its label, then its value large and in mono. The value sits at the figure's foot, so a label
 * that wraps to two lines does not lower its value below the others' (L42).
 */
export function StatTile({ testId, label, info, position, count = 4, children }: StatTileProps) {
  return (
    <div
      data-testid={testId}
      // From md no column narrows below its value: the value's quiet part wraps instead (L42).
      className={cn(
        "flex min-w-0 flex-col px-4 py-3 md:min-w-auto md:px-[18px] md:pb-[18px] md:pt-4",
        tileRules(position, count),
      )}
    >
      {/* The label asks its column for its longest word only, then fills it: the values decide the widths and a
          long label wraps (L42). */}
      <dt className="mb-1 flex w-min min-w-full items-center gap-1 text-[12.5px] text-ink-3">
        <span>{label}</span>
        {info}
      </dt>
      {/* 18 px: five figures share the row beside the aside. One line, the quiet part under the lead only where
          the column cannot hold both (L42). */}
      <dd className="mt-auto flex flex-wrap items-baseline font-mono text-lg font-medium tabular-nums">{children}</dd>
    </div>
  );
}

/** The currency beside a lead figure: 12 px, quiet, 4 px apart (`.stat .u`). */
export function StatUnit({ currency }: { currency: string }) {
  return <span className="ml-1 font-sans text-xs font-normal text-ink-3">{currency}</span>;
}
