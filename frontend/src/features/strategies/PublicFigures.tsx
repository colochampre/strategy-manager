import { Clock, ListChecks, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PublicStrategy } from "@/shared/api/types";
import { amountText, parseDecimal, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { IconTip } from "@/shared/ui/Tooltip";

const DAY_MS = 86_400_000;
/** What a figure shows when there is nothing true to say yet. */
const NO_FIGURE = "—";

interface PublicFiguresProps {
  strategy: PublicStrategy;
  /** An explanation's button, drawn beside the return's label. */
  returnInfo?: ReactNode;
  /** An explanation's button, drawn beside the capital's label. */
  capitalInfo?: ReactNode;
}

interface FigureProps {
  label: string;
  testId: string;
  value: string;
  tone?: string | undefined;
  info?: ReactNode;
  /** Drawn in place of the label, which then names it and explains it on hover. */
  icon?: LucideIcon;
}

function Figure({ label, testId, value, tone = "text-ink", info, icon }: FigureProps) {
  return (
    // The label takes the room left, so a label that wraps never lowers its figure below the others in the row.
    <div className="flex flex-col justify-between gap-0.5">
      <dt className="flex items-start text-xs text-ink-3">
        {icon === undefined ? label : <IconTip icon={icon} label={label} />}
        {info}
      </dt>
      <dd data-testid={testId} className={cn("font-mono text-sm", tone)}>
        {value}
      </dd>
    </div>
  );
}

/** Who wrote a strategy and the market it trades: what names it beside its name, on the list and on its page. */
export function PublicOrigin({ strategy }: Pick<PublicFiguresProps, "strategy">) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-0.5">
      <p data-testid="public-origin" className="text-xs text-ink-2">
        {t("strategies.public.by", { name: strategy.author_name })}
      </p>
      <p data-testid="public-market" className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
        {`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency}`}
      </p>
    </div>
  );
}

/**
 * The public record (decisions 28, 30 and 34): age, closed trades, the return, how many trade it live and the
 * one capital figure. A return is only claimed once a real trade of the author's has closed, and until then the
 * figure says so in words. A capital that is absent, under the server's brake, is told apart from a capital of
 * zero.
 */
export function PublicFigures({ strategy, returnInfo, capitalInfo }: PublicFiguresProps) {
  const { t, i18n } = useTranslation();
  const created = Date.parse(strategy.created_at);
  const age = Number.isNaN(created)
    ? NO_FIGURE
    : t("strategies.public.ageDays", { count: Math.floor((Date.now() - created) / DAY_MS) });
  const ratio = strategy.closed_trade_count === 0 ? null : parseDecimal(strategy.unleveraged_return_before_fees);
  const capital = strategy.capital === null ? null : parseDecimal(strategy.capital);

  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
      <Figure icon={Clock} label={t("strategies.public.age")} testId="public-age" value={age} />
      <Figure
        icon={ListChecks}
        label={t("strategies.public.trades")}
        testId="public-trades"
        value={String(strategy.closed_trade_count)}
      />
      <Figure
        icon={TrendingUp}
        label={t("strategies.public.return")}
        testId="public-return"
        value={
          strategy.closed_trade_count === 0
            ? t("strategies.public.noRealTrade")
            : ratio === null
              ? NO_FIGURE
              : percentText(ratio, i18n.language)
        }
        tone={ratio === null ? undefined : toneClass(ratio)}
        info={returnInfo}
      />
      <Figure label={t("strategies.public.live")} testId="public-live" value={String(strategy.live_subscribers)} />
      <Figure
        label={t("strategies.public.capital")}
        testId="public-capital"
        value={
          capital === null
            ? NO_FIGURE
            : `${amountText(capital, strategy.settlement_currency, i18n.language)} ${strategy.settlement_currency}`
        }
        info={capitalInfo}
      />
    </dl>
  );
}
