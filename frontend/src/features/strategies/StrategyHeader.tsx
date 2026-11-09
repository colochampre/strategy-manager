import { useId, useState } from "react";
import { Webhook } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { AuthorCapital } from "@/features/strategies/AuthorCapital";
import { EnabledBadge } from "@/features/strategies/StrategyCard";
import { StrategyTitle } from "@/features/strategies/StrategyTitle";
import { UptimeSummary } from "@/features/strategies/UptimeSummary";
import { WebhookMessage } from "@/features/strategies/WebhookMessage";
import type { Strategy } from "@/shared/api/types";

interface StrategyHeaderProps {
  strategy: Strategy;
}

/** The way back to the list; the arrow is decoration, so the link's name is the text alone. */
export function BackToStrategies() {
  const { t } = useTranslation();
  return (
    <Link to="/strategies/authored" className="font-mono text-xs text-ink-3 hover:text-ink-2">
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
 * UNMOUNTED: a regenerated secret that was on screen then leaves the mutation
 * cache, and opening it again starts from the placeholder.
 */
export function StrategyHeader({ strategy }: StrategyHeaderProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const archived = strategy.archived_at !== null;

  return (
    <header className="flex flex-col gap-1.5">
      <BackToStrategies />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StrategyTitle strategy={strategy} />
        <EnabledBadge enabled={strategy.enabled} archived={archived} testId="strategy-status" />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 sm:ml-auto"
        >
          <Webhook aria-hidden="true" className="size-4 shrink-0" />
          {t("strategies.webhook.open")}
        </button>
      </div>
      <p className="font-mono text-xs text-ink-2">
        {`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency} · `}
        <UptimeSummary uptime={strategy.uptime} />
      </p>
      <p data-testid="strategy-subscribers" className="font-mono text-xs text-ink-2">
        {t("strategies.row.subscribers", { count: strategy.subscribers, live: strategy.live_subscribers })}
      </p>
      <AuthorCapital strategy={strategy} className="font-mono text-xs text-ink-2" />
      <div id={panelId} className="mt-2">
        {open && <WebhookMessage strategyId={strategy.id} secretLast4={strategy.secret_last4} archived={archived} />}
      </div>
    </header>
  );
}
