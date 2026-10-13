import { useId } from "react";
import { useTranslation } from "react-i18next";

import { OrderLine } from "@/features/positions/MarkLine";
import { OpenReadState } from "@/features/positions/OpenReadState";
import { PositionsTable } from "@/features/positions/PositionsTable";
import { ofExchange, ofStrategy, unmatched, useOpenPositions } from "@/shared/api/positions";
import type { OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";
import { timeOfAnswerText } from "@/shared/lib/figure-text";

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
 * the WHOLE answer (a strategy's page shows its positions wherever the ledger put them) and does not wait for
 * the exchange scope. It counts what its own exchange holds that no strategy owns: while that is not empty the
 * section never says "No open position.", because one of those elements may be this strategy's own. A failed
 * first read is an error with "Read again", never "No open position."; a failed refresh keeps the last answer.
 */
export function OpenPositionsSection({ strategy }: OpenPositionsSectionProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const open = useOpenPositions();
  const locale = i18n.resolvedLanguage ?? "en";

  const heading = (
    <h2 id={headingId} className="font-display text-base font-semibold text-ink">
      {t("positions.table.title")}
    </h2>
  );

  if (open.data === undefined) {
    return (
      <section aria-labelledby={headingId} className="flex flex-col gap-3">
        {heading}
        <OpenReadState status={open.status} errorUpdateCount={open.errorUpdateCount} />
      </section>
    );
  }

  const answer = open.data;
  const mine = ofStrategy(answer, strategy.id);
  const nobodys = unmatched(ofExchange(answer, strategy.exchange));
  const unmatchedCount = nobodys.positions.length + nobodys.orders.length;
  const sentence = unmatchedCount > 0 && (
    <p className="text-sm text-ink">{t("positions.table.unmatched", { count: unmatchedCount })}</p>
  );
  const lastRead = timeOfAnswerText(answer.as_of, answer.as_of, locale, true) ?? answer.as_of;
  const orders = mine.orders.length > 0 && (
    <ul className="flex flex-col gap-1.5">
      {mine.orders.map((order) => (
        <li key={order.attempt_id}>
          <OrderLine order={order} asOf={answer.as_of} />
        </li>
      ))}
    </ul>
  );

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      {heading}
      <div aria-live="polite" className="flex flex-col gap-1">
        {open.status === "error" && <p className="text-sm text-loss">{t("positions.state.stale", { time: lastRead })}</p>}
      </div>
      {mine.positions.length === 0 ? (
        <>
          {sentence || <p className="text-sm text-ink-3">{t("positions.table.empty")}</p>}
          {orders}
        </>
      ) : (
        <>
          <PositionsTable
            variant="strategy"
            positions={mine.positions}
            asOf={answer.as_of}
            currency={strategy.settlement_currency}
            labelledBy={headingId}
          />
          {orders}
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
