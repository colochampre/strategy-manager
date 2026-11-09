import { Coins } from "lucide-react";
import { useTranslation } from "react-i18next";

import { OpenMarks } from "@/features/positions/OpenMarks";
import type { AuthoredCard } from "@/features/strategies/card-figures";
import { useEnableQuestion } from "@/features/strategies/EnableDialog";
import { Figure } from "@/features/strategies/PublicFigures";
import { StrategyCard } from "@/features/strategies/StrategyCard";
import type { Strategy } from "@/shared/api/types";
import { amountText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";

interface StrategyRowProps {
  strategy: Strategy;
  /** The card's figures, read by the list so it can order its cards by them. */
  card: AuthoredCard;
}

/**
 * One of the author's strategies, as the same card Explore and My subscriptions draw. It adds the PnL, the one
 * figure only the author has, the author's open positions, and the enable switch last: the switch is the only
 * control, it asks before it changes anything, and a refused or failed change says so in that question instead of
 * silently snapping back.
 */
export function StrategyRow({ strategy, card }: StrategyRowProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const question = useEnableQuestion(strategy);
  const archived = strategy.archived_at !== null;
  const pnl = card.pnl;

  return (
    <StrategyCard
      prefix="strategy"
      rowTestId="strategy-row"
      to={`/strategies/${strategy.id}`}
      name={strategy.name}
      archived={archived}
      market={[strategy.venue, strategy.allowed_pairs.join(", ")].filter((part) => part !== "").join(" · ")}
      since={strategy.created_at}
      sinceKind="age"
      uptime={strategy.uptime}
      figures={card.figures}
      figuresError={card.failed ? t("strategies.row.performanceError") : null}
      trailing={
        card.failed ? undefined : (
          <Figure
            icon={Coins}
            label={t("strategies.card.pnl")}
            testId="strategy-pnl"
            value={
              pnl === undefined
                ? "…"
                : pnl === null
                  ? "—"
                  : `${amountText(pnl, strategy.settlement_currency, locale, true)} ${strategy.settlement_currency}`
            }
            tone={pnl === undefined || pnl === null ? undefined : toneClass(pnl)}
          />
        )
      }
      action={
        <div className="flex flex-col items-end gap-1">
          <button
            type="button"
            role="switch"
            aria-checked={strategy.enabled}
            aria-label={t("strategies.row.enable", { name: strategy.name })}
            disabled={archived || question.busy}
            onClick={question.ask}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-rule transition-colors disabled:opacity-50",
              strategy.enabled ? "bg-gain" : "bg-panel-2",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "inline-block size-4 rounded-full bg-ink transition-transform",
                strategy.enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
          {question.dialog}
        </div>
      }
      marks={<OpenMarks strategy={strategy} />}
    />
  );
}
