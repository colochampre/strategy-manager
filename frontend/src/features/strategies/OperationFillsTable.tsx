import { useTranslation } from "react-i18next";

import { dateTimeText, figureText } from "@/features/strategies/format";
import { useOperationFills } from "@/shared/api/performance";

/** The route serves at most this many fills and says so with `truncated` (design § D). */
const FILLS_CAP = 200;

const KEY = "strategies.performance.trades";
const CELL = "border-b border-rule-soft py-2 pr-3";
const HEADER = "border-b border-rule py-2 pr-3 font-medium";

interface OperationFillsTableProps {
  strategyId: string;
  allocationId: string;
  /** The operation's base currency, written in the Quantity heading. */
  baseCurrency: string | null;
  /** The operation's own rehearsal mark; a fill whose flag differs carries the Dry run tag. */
  operationRehearsal: boolean;
}

/**
 * The individual fills of one operation (decision 43). Mounting it is what asks for them, so no
 * request is made for a row nobody opened. Three states: a loading line, an error with Try again,
 * and a real table with a caption; when the route says it cut the list, one sentence says so. A
 * body that fails validation is the error state, never a partial table (`fetchOperationFills`).
 */
export function OperationFillsTable({
  strategyId,
  allocationId,
  baseCurrency,
  operationRehearsal,
}: OperationFillsTableProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const fills = useOperationFills(strategyId, allocationId);

  if (fills.data === undefined && fills.status === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p role="alert" className="text-sm text-loss">
          {t(`${KEY}.detail.fills.error`)}
        </p>
        <button
          type="button"
          onClick={() => void fills.refetch()}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t(`${KEY}.detail.fills.retry`)}
        </button>
      </div>
    );
  }
  if (fills.data === undefined) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t(`${KEY}.detail.fills.loading`)}
      </p>
    );
  }

  const unreadable = t(`${KEY}.cellUnreadable`);
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[13px] tabular-nums">
          <caption className="pb-2 text-left font-display text-sm font-semibold text-ink">
            {t(`${KEY}.detail.fills.title`)}
          </caption>
          <thead>
            <tr className="text-right text-[10px] uppercase tracking-[0.09em] text-ink-3">
              <th scope="col" className={`${HEADER} text-left`}>
                {t(`${KEY}.detail.fills.time`)}
              </th>
              <th scope="col" className={`${HEADER} text-left`}>
                {t(`${KEY}.detail.fills.side`)}
              </th>
              <th scope="col" className={HEADER}>
                {t(`${KEY}.detail.fills.price`)}
              </th>
              <th scope="col" className={HEADER}>
                {t(`${KEY}.detail.fills.quantity`, { base: baseCurrency })}
              </th>
              <th scope="col" className={HEADER}>
                {t(`${KEY}.detail.fills.fee`)}
              </th>
            </tr>
          </thead>
          <tbody className="text-right text-ink-2">
            {fills.data.fills.map((fill, index) => (
              <tr key={`${fill.filled_at}-${index}`}>
                <td className={`${CELL} text-left`}>{dateTimeText(fill.filled_at, locale)}</td>
                <td className={`${CELL} text-left`}>
                  {t(`${KEY}.detail.fills.sides.${fill.side}`)}
                  {fill.rehearsal !== operationRehearsal && (
                    <span className="block font-sans text-[11px] text-decision">{t(`${KEY}.rehearsal`)}</span>
                  )}
                </td>
                <td className={CELL}>{figureText(fill.price) ?? unreadable}</td>
                <td className={CELL}>{figureText(fill.quantity) ?? unreadable}</td>
                <td className={CELL}>
                  {figureText(fill.fee) ?? unreadable} {fill.fee_currency}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {fills.data.truncated && (
        <p className="text-sm text-ink-3">{t(`${KEY}.detail.fills.truncated`, { count: FILLS_CAP })}</p>
      )}
    </div>
  );
}
