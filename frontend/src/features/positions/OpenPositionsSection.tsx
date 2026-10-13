import { useId } from "react";
import { useTranslation } from "react-i18next";

import { PositionsTable } from "@/features/positions/PositionsTable";
import { ofExchange, ofStrategy, unmatched, useOpenPositions } from "@/shared/api/positions";
import type { OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";

interface OpenPositionsSectionProps {
  strategy: Strategy;
}

/**
 * The notes, each drawn only when a row on screen makes it true, in this order: the dry-run note, the note of
 * a position of both origins, and the margin note (true of any position). No position, no note.
 */
function noteKeys(positions: OpenPosition[]): string[] {
  if (positions.length === 0) return [];
  return [
    positions.some((position) => position.origin === "rehearsal") ? "positions.note.rehearsal" : null,
    positions.some((position) => position.origin === "mixed") ? "positions.note.mixed" : null,
    "positions.note.margin",
  ].filter((key): key is string => key !== null);
}

/**
 * The strategy's open positions, above its closed trades. It selects the strategy's own elements by id over
 * the WHOLE answer (a strategy's page shows its positions wherever the ledger put them), and counts what its
 * own exchange holds that no strategy owns: while that is not empty the section never says "No open
 * position.", because one of those elements may be this strategy's own.
 */
export function OpenPositionsSection({ strategy }: OpenPositionsSectionProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const open = useOpenPositions();
  if (open.data === undefined) return null;

  const mine = ofStrategy(open.data, strategy.id);
  const nobodys = unmatched(ofExchange(open.data, strategy.exchange));
  const unmatchedCount = nobodys.positions.length + nobodys.orders.length;
  const sentence = unmatchedCount > 0 && (
    <p className="text-sm text-ink">{t("positions.table.unmatched", { count: unmatchedCount })}</p>
  );

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("positions.table.title")}
      </h2>
      {mine.positions.length === 0 ? (
        sentence || <p className="text-sm text-ink-3">{t("positions.table.empty")}</p>
      ) : (
        <>
          <PositionsTable
            variant="strategy"
            positions={mine.positions}
            asOf={open.data.as_of}
            currency={strategy.settlement_currency}
            labelledBy={headingId}
          />
          {sentence}
        </>
      )}
      <div className="flex flex-col gap-1.5">
        {noteKeys(mine.positions).map((key) => (
          <p key={key} className="text-sm text-ink-2">
            {t(key)}
          </p>
        ))}
      </div>
    </section>
  );
}
