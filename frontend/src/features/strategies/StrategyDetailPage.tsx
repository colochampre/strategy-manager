import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";

import { AllowedPairsEditor } from "@/features/strategies/AllowedPairsEditor";
import { ArchiveControl } from "@/features/strategies/ArchiveControl";
import { DeleteStrategyControl } from "@/features/strategies/DeleteStrategyControl";
import { EnablementHistory } from "@/features/strategies/EnablementHistory";
import { EnableToggle } from "@/features/strategies/EnableToggle";
import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { BackToStrategies, StrategyHeader } from "@/features/strategies/StrategyHeader";
import { StrategyPerformance } from "@/features/strategies/StrategyPerformance";
import { TradesTable } from "@/features/strategies/TradesTable";
import { ApiError } from "@/shared/api/client";
import { useStrategy } from "@/shared/api/strategies";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * One strategy. The left column is its header and uptime and its performance (the
 * Overview's ledger line, chart and month grid for this strategy, then the By
 * pair table). Its closed trades are the widest thing on the page, so they are a
 * full-width section under the two-column grid (decision 43, design § F). The webhook block is a disclosure
 * opened from the header (decision: 12f.8 superseded). The settings column holds the share of the pool per
 * trade first, then the allowed-pairs editor, the enable switch, that switch's history and, last, the archive control. The delete control has its
 * own block at the very bottom, below archive (design addendum 9x § H): a
 * different act, never beside the switch.
 *
 * The exchange tabs follow the strategy: once it is loaded, the scope is set to
 * its exchange (design § 15), so the tabs never claim another exchange than the
 * one this page describes. An exchange that has no pool is left alone.
 */
export function StrategyDetailPage() {
  const { t } = useTranslation();
  const { strategyId = "" } = useParams();
  const strategy = useStrategy(strategyId);
  const scope = useExchangeScope();

  const strategyExchange = strategy.data?.exchange;
  const scopeSelect = scope.status === "ready" ? scope.select : null;
  const scopeExchange = scope.status === "ready" ? scope.exchange : null;
  const scopeKnowsIt = scope.status === "ready" && strategyExchange !== undefined && scope.options.includes(strategyExchange);
  useEffect(() => {
    if (scopeKnowsIt && strategyExchange !== scopeExchange) scopeSelect?.(strategyExchange as string);
  }, [scopeKnowsIt, strategyExchange, scopeExchange, scopeSelect]);

  if (strategy.status === "pending") {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.detail.loading")}
      </p>
    );
  }

  if (strategy.status === "error") {
    const missing = strategy.error instanceof ApiError && strategy.error.status === 404;
    return (
      <div className="flex flex-col gap-3">
        <BackToStrategies />
        <p role={missing ? undefined : "alert"} className="text-sm text-ink-2">
          {t(missing ? "strategies.detail.notFound" : "strategies.detail.error")}
        </p>
      </div>
    );
  }

  const subject = strategy.data;
  return (
    <div className="flex flex-col gap-8">
      <div className="grid gap-9 lg:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <StrategyHeader strategy={subject} />
          <StrategyPerformance key={subject.id} strategyId={subject.id} />
        </div>
        <aside
          aria-label={t("strategies.detail.settings")}
          className="flex flex-col gap-5 self-start rounded-lg border border-rule bg-panel p-5"
        >
          <h2 className="font-display text-base font-semibold text-ink">{t("strategies.detail.settings")}</h2>
          <PoolShareEditor key={subject.id} strategy={subject} />
          <AllowedPairsEditor strategy={subject} />
          <div className="flex flex-col gap-2 border-t border-rule pt-4">
            <EnableToggle strategy={subject} />
            <EnablementHistory strategyId={subject.id} />
            <ArchiveControl strategy={subject} />
          </div>
        </aside>
      </div>
      <TradesTable strategyId={subject.id} currency={subject.settlement_currency} />
      <DeleteStrategyControl strategy={subject} />
    </div>
  );
}
