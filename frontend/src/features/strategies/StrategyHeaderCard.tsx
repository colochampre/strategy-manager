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

/** The row's figures, two a row on a phone and four from `md`, a rule over it and out to the card's edges. */
export function StatsRow({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <dl
      data-testid={testId}
      className="-mx-4 mt-[18px] grid min-w-0 grid-cols-2 border-t border-rule md:-mx-6 md:mt-[22px] md:grid-cols-4"
    >
      {children}
    </dl>
  );
}

/**
 * Where the rules between figures fall, by the figure's place in the row of four: two a row on a phone, four from
 * `md`, as the dashboard's header card rules them. The first is set in from the card's edge by the card's own padding.
 */
const TILE_RULES = [
  "border-b border-r border-rule md:border-b-0 md:pl-6",
  "border-b border-rule md:border-b-0 md:border-r",
  "border-r border-rule",
  "",
] as const;

interface StatTileProps {
  testId: string;
  label: string;
  /** The (i) after the label, for a figure that has one. */
  info?: ReactNode;
  /** The figure's place in the row, from 0. */
  position: 0 | 1 | 2 | 3;
  /** The lead figure, then its second line, if it has one. */
  children: ReactNode;
}

/** One figure of the row: its label, then its value large and in mono. */
export function StatTile({ testId, label, info, position, children }: StatTileProps) {
  return (
    <div
      data-testid={testId}
      className={cn("min-w-0 px-4 py-3 md:px-[18px] md:pb-[18px] md:pt-4", TILE_RULES[position])}
    >
      <dt className="mb-1 flex items-center gap-1 text-[12.5px] text-ink-3">
        <span>{label}</span>
        {info}
      </dt>
      <dd className="font-mono text-xl font-medium tabular-nums">{children}</dd>
    </div>
  );
}

/** The currency beside a lead figure: 12 px, quiet, 4 px apart (`.stat .u`). */
export function StatUnit({ currency }: { currency: string }) {
  return <span className="ml-1 font-sans text-xs font-normal text-ink-3">{currency}</span>;
}

/** The line under a lead figure (`.stat .s2`): 12.5 px, quiet unless `className` gives it a tone. */
export function SecondLine({
  testId,
  className,
  children,
}: {
  testId?: string;
  className?: string | undefined;
  children: ReactNode;
}) {
  return (
    <span
      data-testid={testId}
      className={cn("mt-[3px] block whitespace-nowrap font-sans text-[12.5px] font-normal text-ink-3", className)}
    >
      {children}
    </span>
  );
}
