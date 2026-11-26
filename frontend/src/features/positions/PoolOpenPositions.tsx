import { useId } from "react";
import { useTranslation } from "react-i18next";

import { OpenReadState } from "@/features/positions/OpenReadState";
import { PositionsTable } from "@/features/positions/PositionsTable";
import { ofPool, useOpenPositions } from "@/shared/api/positions";
import type { OpenPool } from "@/shared/api/positions";
import { timeOfAnswerText } from "@/shared/lib/figure-text";
import { Card } from "@/shared/ui/Card";
import { CountChip } from "@/shared/ui/CountChip";

interface PoolOpenPositionsProps {
  pool: OpenPool;
}

/**
 * One pool's open positions on the Overview, every one of them, dry run and live together, each with its
 * origin and the strategy's name first (examples 22 and 24), in a card of its own with the count beside the title
 * (ex1). It selects by the pool's three values and never by the exchange alone (rule 7), keeps the server's order,
 * and draws no order in flight (owner decision Q8, 2026-10-13) and no note. It does not depend on the pool's
 * performance report.
 *
 * The card is drawn only to hold a position, or to say the read failed (L36): with nothing held it draws nothing,
 * and the header card's count says 0. A failed first read is an error with "Read again", under the heading: the
 * header card's count is absent then, never a zero (design § K row 21). A failed refresh keeps the last answer.
 */
export function PoolOpenPositions({ pool }: PoolOpenPositionsProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const open = useOpenPositions();
  const locale = i18n.resolvedLanguage ?? "en";
  const title = t("positions.table.title");

  if (open.data === undefined) {
    return (
      <Card title={title} headingId={headingId}>
        <OpenReadState status={open.status} errorUpdateCount={open.errorUpdateCount} />
      </Card>
    );
  }

  const answer = open.data;
  const mine = ofPool(answer, pool);
  // Nothing held and the last read good: no card (L36). The header card's count says 0. A failed refresh keeps the
  // card, so its red line is not hidden with it.
  if (mine.positions.length === 0 && open.status !== "error") return null;
  const lastRead = timeOfAnswerText(answer.as_of, answer.as_of, locale, true) ?? answer.as_of;

  return (
    <Card
      title={title}
      headingId={headingId}
      dense
      action={<CountChip testId="positions-count">{t("positions.table.count", { count: mine.positions.length })}</CountChip>}
    >
      <div className="flex flex-col gap-4">
        {/* Empty most of the time: it takes back the gap it would otherwise leave above the table (ex1). */}
        <div aria-live="polite" className="flex flex-col gap-1 empty:-mb-4">
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
      </div>
    </Card>
  );
}
