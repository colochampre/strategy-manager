import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { UptimeSummary } from "@/features/strategies/UptimeSummary";
import { WebhookMessage } from "@/features/strategies/WebhookMessage";
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

/**
 * The way back to the list, the strategy's name and status, its pool and its
 * uptime, and the button that opens "Connect a TradingView alert". The block
 * opens as a panel under the header, in the page flow (the JSON is long and has
 * to be selected, so it is not a popover). It is closed by default and, closed,
 * UNMOUNTED: `WebhookMessage`'s cleanup then evicts a revealed secret from the
 * query cache, and opening it again starts from the placeholder.
 */
export function StrategyHeader({ strategy }: StrategyHeaderProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const panelId = useId();
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
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 sm:ml-auto"
        >
          {t("strategies.webhook.open")}
        </button>
      </div>
      <p className="font-mono text-xs text-ink-2">
        {`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency} · `}
        <UptimeSummary uptime={strategy.uptime} />
      </p>
      <div id={panelId} className="mt-2">
        {open && <WebhookMessage strategyId={strategy.id} />}
      </div>
    </header>
  );
}
