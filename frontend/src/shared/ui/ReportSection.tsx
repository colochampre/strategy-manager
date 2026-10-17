import type { ReactNode } from "react";

/**
 * The frame around one report section, the strategy card's own (`rounded-md border border-rule bg-panel px-4 py-3`).
 * Every frame class is `md:`-prefixed: below 768 px the section draws nothing, because the positions and the booked
 * items already draw each item as a bordered card there and a frame would nest a card in a card (owner decision 67 Q4, Q7).
 */
export function ReportSection({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="report-section"
      className="min-w-0 md:rounded-md md:border md:border-rule md:bg-panel md:px-4 md:py-3"
    >
      {children}
    </div>
  );
}
