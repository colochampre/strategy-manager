import { useId, useState } from "react";
import { Webhook } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { EnabledBadge } from "@/features/strategies/StrategyCard";
import { StrategyPageHeader } from "@/features/strategies/StrategyPageHeader";
import { StrategyTitle } from "@/features/strategies/StrategyTitle";
import { WebhookMessage } from "@/features/strategies/WebhookMessage";
import { useMe } from "@/shared/api/me";
import type { Strategy } from "@/shared/api/types";
import { GAIN_OUTLINE } from "@/shared/ui/button-styles";

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
 * The header another author's page draws (owner, 2026-11-17): the way back, the name with its pencil, the status, who
 * wrote it and its dated market; and here the button that opens "Connect a TradingView alert". Its subscribers and
 * capital are AuM's, in the figures under Performance. The block opens as a panel under the header, in the page flow
 * (the JSON is long and has to be selected, so it is not a popover). It is closed by default and, closed,
 * UNMOUNTED: a regenerated secret that was on screen then leaves the mutation cache, and opening it again starts
 * from the placeholder.
 */
export function StrategyHeader({ strategy }: StrategyHeaderProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const me = useMe();
  const archived = strategy.archived_at !== null;
  // The name the public page signs it with; the reader's own words while they have chosen none.
  const name = me.data?.displayName ?? null;

  return (
    <StrategyPageHeader
      prefix="strategy"
      back={<BackToStrategies />}
      title={<StrategyTitle strategy={strategy} />}
      status={<EnabledBadge enabled={strategy.enabled} archived={archived} testId="strategy-status" />}
      action={
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          // Drawn as New strategy and I have a code (L40): above the aside it read as a quiet button.
          className={`inline-flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-4 text-sm ${GAIN_OUTLINE}`}
        >
          <Webhook aria-hidden="true" className="size-4 shrink-0" />
          {t("strategies.webhook.open")}
        </button>
      }
      byline={name === null ? t("strategies.subscriptions.yours") : t("strategies.public.by", { name })}
      market={`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency}`}
      since={strategy.created_at}
    >
      {/* Closed, it takes no room, so the page under the header starts where another author's does. */}
      <div id={panelId} className={open ? "mt-2" : "hidden"}>
        {open && <WebhookMessage strategyId={strategy.id} secretLast4={strategy.secret_last4} archived={archived} />}
      </div>
    </StrategyPageHeader>
  );
}
