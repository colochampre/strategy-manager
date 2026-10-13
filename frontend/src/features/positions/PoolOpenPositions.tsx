import { useId } from "react";
import { useTranslation } from "react-i18next";

import { OpenReadState } from "@/features/positions/OpenReadState";
import { PositionsTable } from "@/features/positions/PositionsTable";
import { ofPool, useOpenPositions } from "@/shared/api/positions";
import type { OpenPool } from "@/shared/api/positions";
import { timeOfAnswerText } from "@/shared/lib/figure-text";

interface PoolOpenPositionsProps {
  pool: OpenPool;
}

/**
 * One pool's open positions on the Overview, every one of them, dry run and live together, each with its
 * origin and the strategy's name first (examples 22 and 24). It selects by the pool's three values and never by
 * the exchange alone (rule 7), keeps the server's order, and draws no order in flight (owner decision Q8,
 * 2026-10-13) and no note. It does not depend on the pool's performance report.
 *
 * The heading is always drawn. A failed first read is an error with "Read again", never "No open position.":
 * the Overview's count is absent both when nothing is open and when the read failed, so this sentence is what
 * keeps an absent count from being read as zero (design § K row 21). A failed refresh keeps the last answer.
 */
export function PoolOpenPositions({ pool }: PoolOpenPositionsProps) {
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
  const mine = ofPool(answer, pool);
  const lastRead = timeOfAnswerText(answer.as_of, answer.as_of, locale, true) ?? answer.as_of;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      {heading}
      <div aria-live="polite" className="flex flex-col gap-1">
        {open.status === "error" && <p className="text-sm text-loss">{t("positions.state.stale", { time: lastRead })}</p>}
      </div>
      {mine.positions.length === 0 ? (
        <p className="text-sm text-ink-3">{t("positions.table.empty")}</p>
      ) : (
        <PositionsTable
          variant="pool"
          positions={mine.positions}
          asOf={answer.as_of}
          currency={pool.settlement_currency}
          labelledBy={headingId}
        />
      )}
    </section>
  );
}
