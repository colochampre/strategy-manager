import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { TradeStrategyChoice } from "@/shared/api/trades";
import { exchangeName } from "@/shared/exchanges/exchange-name";

export type Period = "7" | "30" | "90" | "all";

export const PERIODS: readonly Period[] = ["7", "30", "90", "all"];

export interface TradeFilters {
  period: Period;
  /** A strategy id; empty for every strategy. */
  strategyId: string;
  /** An exchange id; empty for every exchange. */
  exchange: string;
  /** The instant the period counts back from, taken when the period is chosen so the request does not change on its own. */
  anchor: number;
}

export const DEFAULT_PERIOD: Period = "30";

const SELECT =
  "h-9 min-w-0 rounded-lg border border-rule-strong bg-panel-2 px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-40 flex-1 flex-col gap-1.5">
      <label htmlFor={id} className="text-[12.5px] text-ink-3">
        {label}
      </label>
      {children}
    </div>
  );
}

interface Props {
  filters: TradeFilters;
  strategies: readonly TradeStrategyChoice[];
  exchanges: readonly string[];
  onChange: (change: Partial<Pick<TradeFilters, "period" | "strategyId" | "exchange">>) => void;
  onClear: () => void;
}

/** The ex4 filters card: Period, Strategy, Exchange and Clear filters. */
export function TradesFilters({ filters, strategies, exchanges, onChange, onClear }: Props) {
  const { t, i18n } = useTranslation();
  const periodId = useId();
  const strategyId = useId();
  const exchangeId = useId();
  const periodKey: Record<Period, string> = {
    "7": "trades.filters.last7",
    "30": "trades.filters.last30",
    "90": "trades.filters.last90",
    all: "trades.filters.all",
  };
  const exchangeOptions = [...exchanges].sort((a, b) => exchangeName(t, i18n, a).localeCompare(exchangeName(t, i18n, b)));
  return (
    <section
      aria-label={t("trades.filters.label")}
      className="flex flex-wrap items-end gap-4 rounded-[10px] border border-rule bg-panel p-[22px]"
    >
      <Field label={t("trades.filters.period")} id={periodId}>
        <select
          id={periodId}
          value={filters.period}
          onChange={(event) => onChange({ period: event.target.value as Period })}
          className={SELECT}
        >
          {PERIODS.map((period) => (
            <option key={period} value={period}>
              {t(periodKey[period])}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("trades.filters.strategy")} id={strategyId}>
        <select
          id={strategyId}
          value={filters.strategyId}
          onChange={(event) => onChange({ strategyId: event.target.value })}
          className={SELECT}
        >
          <option value="">{t("trades.filters.allStrategies")}</option>
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("trades.filters.exchange")} id={exchangeId}>
        <select
          id={exchangeId}
          value={filters.exchange}
          onChange={(event) => onChange({ exchange: event.target.value })}
          className={SELECT}
        >
          <option value="">{t("trades.filters.allExchanges")}</option>
          {exchangeOptions.map((exchange) => (
            <option key={exchange} value={exchange}>
              {exchangeName(t, i18n, exchange)}
            </option>
          ))}
        </select>
      </Field>
      <button
        type="button"
        onClick={onClear}
        className="inline-flex h-9 shrink-0 items-center rounded-lg border border-rule bg-panel px-3.5 text-sm text-ink hover:bg-panel-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
      >
        {t("trades.filters.clear")}
      </button>
    </section>
  );
}
