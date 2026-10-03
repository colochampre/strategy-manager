import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { UptimeSummary } from "@/features/strategies/UptimeSummary";
import type { Strategy } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";

interface StrategyHeaderProps {
  strategy: Strategy;
}

/** The way back to the list; the arrow is decoration, so the link's name is the text alone. */
export function BackToStrategies() {
  const { t } = useTranslation();
  return (
    <Link to="/strategies" className="font-mono text-xs text-ink-3 hover:text-ink-2">
      <span aria-hidden="true">← </span>
      {t("strategies.detail.back")}
    </Link>
  );
}

/** The way back to the list, the strategy's name and status, its pool and its uptime. */
export function StrategyHeader({ strategy }: StrategyHeaderProps) {
  const { t } = useTranslation();
  const archived = strategy.archived_at !== null;
  const status = archived ? "strategies.row.archived" : strategy.enabled ? "strategies.detail.enabled" : "strategies.detail.disabled";

  return (
    <header className="flex flex-col gap-1.5">
      <BackToStrategies />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="font-display text-3xl font-bold text-ink">{strategy.name}</h1>
        <span
          className={cn(
            "rounded border px-2 py-1 font-mono text-[11px] uppercase tracking-[0.12em]",
            strategy.enabled && !archived ? "border-gain text-gain" : "border-rule text-ink-3",
          )}
        >
          {t(status)}
        </span>
      </div>
      <p className="font-mono text-xs text-ink-2">
        {`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency} · `}
        <UptimeSummary uptime={strategy.uptime} />
      </p>
    </header>
  );
}
