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
      // A container: the figure row lays itself out by the card's width, which the folded sidebar changes too (L44).
      className="@container rounded-[10px] border border-rule bg-panel px-4 pt-[18px] md:px-6 md:pt-[22px]"
    >
      {about}
      {children}
    </section>
  );
}

/** How many figures a row holds: four, or five where the PnL and the return are two (L42). */
export type RowCount = 4 | 5;

/**
 * The row's columns by the card's width (L44). Four figures: two a row, then one row from 35rem. Five: two a row,
 * then from 22rem the PnL and the Return over the other three (six tracks, spanned 3+3 and 2+2+2), then one row from
 * 35rem, where the owner measured the five fitting (a 1392 px window). In one row each column is as wide as its figure needs and the room left is shared out, so a long AuM takes it
 * from a short return instead of spilling out of an equal share (L42).
 */
const ROW_GRID: Record<RowCount, string> = {
  4: "@min-[35rem]:grid-cols-[repeat(4,auto)]",
  5: "@min-[22rem]:grid-cols-6 @min-[35rem]:grid-cols-[repeat(5,auto)]",
};

/** The row's figures, a rule over it and out to the card's edges, laid out as `ROW_GRID` says. */
export function StatsRow({ testId, count = 4, children }: { testId: string; count?: RowCount; children: ReactNode }) {
  return (
    <dl
      data-testid={testId}
      className={cn(
        "-mx-4 mt-[18px] grid min-w-0 grid-cols-2 border-t border-rule md:-mx-6 md:mt-[22px]",
        ROW_GRID[count],
      )}
    >
      {children}
    </dl>
  );
}

/**
 * Where each figure sits and where its rules fall, by its place in the row, for every layout of `ROW_GRID`: a rule
 * under every row but the last and between the figures of a row. A figure that starts a row is set in as the card's
 * text is (`md:pl-6`), the dashboard's header card's way. Literal strings, so Tailwind finds every class.
 */
const TILE_RULES: Record<RowCount, readonly string[]> = {
  4: [
    "border-b border-r @min-[35rem]:border-b-0 md:pl-6",
    "border-b @min-[35rem]:border-b-0 @min-[35rem]:border-r",
    "border-r md:@max-[35rem]:pl-6",
    "",
  ],
  5: [
    "border-b border-r @min-[22rem]:col-span-3 @min-[35rem]:col-span-1 @min-[35rem]:border-b-0 md:pl-6",
    "border-b @min-[22rem]:col-span-3 @min-[35rem]:col-span-1 @min-[35rem]:border-b-0 @min-[35rem]:border-r",
    "border-b border-r @min-[22rem]:col-span-2 @min-[22rem]:border-b-0 @min-[35rem]:col-span-1 md:@max-[35rem]:pl-6",
    "border-b @min-[22rem]:col-span-2 @min-[22rem]:border-b-0 @min-[22rem]:border-r @min-[35rem]:col-span-1",
    "col-span-2 @min-[35rem]:col-span-1 md:@max-[22rem]:pl-6",
  ],
};

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
      // In one row no column narrows below its value: the value's quiet part wraps instead (L42).
      className={cn(
        "flex min-w-0 flex-col border-rule px-4 py-3 @min-[35rem]:min-w-auto md:px-[18px] md:pb-[18px] md:pt-4",
        TILE_RULES[count][position],
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
