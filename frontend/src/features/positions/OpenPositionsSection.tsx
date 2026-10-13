import { useId } from "react";

import { PositionsTable } from "@/features/positions/PositionsTable";
import { ofStrategy, useOpenPositions } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";

interface OpenPositionsSectionProps {
  strategy: Strategy;
}

/** STUB (op.3.1): the heading and a table written from defaults. The real section is written in op.3.15. */
export function OpenPositionsSection({ strategy }: OpenPositionsSectionProps) {
  const headingId = useId();
  const open = useOpenPositions();
  if (open.data === undefined) return null;
  const mine = ofStrategy(open.data, strategy.id);
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Open positions</h2>
      <PositionsTable
        variant="strategy"
        positions={mine.positions}
        asOf={open.data.as_of}
        currency={strategy.settlement_currency}
        labelledBy={headingId}
      />
    </section>
  );
}
