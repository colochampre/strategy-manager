import { useTranslation } from "react-i18next";

import { rangeLabel } from "@/features/overview/LedgerLine";
import { useRangeStore } from "@/features/overview/range-store";
import { publicFigures } from "@/features/strategies/card-figures";
import { CardFigureGrid } from "@/features/strategies/StrategyCard";
import { usePublicRecord } from "@/shared/api/public-record";
import type { PublicStrategy } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/amount-text";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

/**
 * Another author's strategy in one row, as its card draws it, at the top of Performance: age, days active, closed
 * trades, return, deepest fall, win rate, subscribers and capital. The return and the fall are the record's and
 * follow the chart's range; while the record is read they say so ("…"), and with no closed trade they are a dash.
 */
export function RecordFigures({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  const record = usePublicRecord(strategy.id);
  const range = useRangeStore((state) => state.range);
  const returnInfo = useInfoDisclosure();
  const capitalInfo = useInfoDisclosure();

  const data = record.status === "pending" ? undefined : record.status === "success" ? record.data : null;
  const traded = data !== undefined && data !== null && data.closed_trade_count > 0;
  const summary = traded ? data.ranges.find((entry) => entry.range === range) : undefined;
  const figures = {
    ...publicFigures(strategy),
    ret: data === undefined ? undefined : summary === undefined ? null : parseDecimal(summary.return),
    deepest: data === undefined ? undefined : traded ? parseDecimal(data.max_drawdown) : null,
  };

  return (
    <div className="flex flex-col gap-2">
      <CardFigureGrid
        testId="record-line"
        // The page's column is narrower than a card, so four a row on every width: two rows, never eight squeezed.
        className="lg:grid-flow-row lg:grid-cols-4"
        prefix="public"
        since={strategy.created_at}
        sinceKind="age"
        uptime={strategy.uptime}
        figures={figures}
        returnLabel={rangeLabel(t, "strategies.report.recordReturn", range)}
        returnInfo={<InfoButton disclosure={returnInfo} label={t("strategies.public.returnInfo")} />}
        capitalInfo={<InfoButton disclosure={capitalInfo} label={t("strategies.public.capitalInfo")} />}
      />
      <InfoText disclosure={returnInfo}>
        <p className="text-xs text-ink-3">{t("strategies.public.returnHint")}</p>
      </InfoText>
      <InfoText disclosure={capitalInfo}>
        <p className="text-xs text-ink-3">{t("strategies.public.capitalHint")}</p>
      </InfoText>
    </div>
  );
}
