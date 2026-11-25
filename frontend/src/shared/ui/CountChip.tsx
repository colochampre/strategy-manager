import type { ReactNode } from "react";

/**
 * The prototype's `.chip-n` (ex1, "3 posiciones"): a count beside a card's title, in a 6 px chip on the ground
 * colour with a 1 px rule. Not a `Pill`: a pill states a status, this states how many.
 */
export function CountChip({ testId, children }: { testId?: string; children: ReactNode }) {
  return (
    <span data-testid={testId} className="rounded-md border border-rule bg-ground px-2.5 py-[3px] text-[12.5px] text-ink">
      {children}
    </span>
  );
}
