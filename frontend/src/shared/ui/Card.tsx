import { type ReactNode, useId } from "react";

import { cn } from "@/shared/lib/cn";

interface CardProps {
  title: string;
  /** What sits right of the title, in the card's header (a small button). */
  action?: ReactNode;
  /** The card of an irreversible action: its border and title are loss-coloured (ex7, "Eliminar cuenta"). */
  danger?: boolean;
  /** A body that starts 14 px under the title instead of 18, for a card that opens with a field (ex6's filter). */
  dense?: boolean;
  children: ReactNode;
}

/** A row of a card's body: the sentence or fact on the left, its control on the right, a soft rule between rows. */
export const CARD_ROW =
  "flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-rule-soft py-4 first:pt-0 last:border-b-0 last:pb-0";

/**
 * The prototype's `.card` (ex6, ex7): a 10 px panel with a 1 px rule, a header of the title (17 px display) with an
 * optional action, and a padded body. One `h2` names the section.
 */
export function Card({ title, action, danger = false, dense = false, children }: CardProps) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className={cn("rounded-[10px] border bg-panel", danger ? "mt-4 border-loss/40" : "border-rule")}
    >
      <div className="flex items-center justify-between gap-3 px-[22px] pt-[18px]">
        <h2 id={headingId} className={cn("font-display text-[17px] font-semibold", danger ? "text-loss" : "text-ink")}>
          {title}
        </h2>
        {action}
      </div>
      <div className={cn("px-[22px] pb-[22px]", dense ? "pt-3.5" : "pt-[18px]")}>{children}</div>
    </section>
  );
}
