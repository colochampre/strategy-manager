import { Calendar, ChartPie, Gauge } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Figure, StrategyFigures, useAgeSince } from "@/features/strategies/PublicFigures";
import { readStored } from "@/features/strategies/share-value";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import type { HeldSubscription, PublicStrategy } from "@/shared/api/types";

/** Explore's figures plus the reader's two: seven, so the row is wider than Explore's five. */
const SEAT_FIGURES_GRID = "grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-7";

interface SubscriptionRowProps {
  held: HeldSubscription;
  /** The strategy as Explore shows it, or undefined: not on the public list, or the list not read. */
  shown: PublicStrategy | undefined;
}

/**
 * One seat, as Explore draws its strategy: the name, the author and the market, the strategy's figures, with the
 * reader's time in it in place of the strategy's age, then the share of the pool and the leverage. It is a summary:
 * the seat is changed and left on the strategy's own page, which the name links to.
 */
function SubscriptionRow({ held, shown }: SubscriptionRowProps) {
  const { t } = useTranslation();
  const age = useAgeSince(held.created_at);
  const author = held.authored
    ? t("strategies.subscriptions.yours")
    : held.author_name === null
      ? t("strategies.subscriptions.noAuthorName")
      : t("strategies.subscriptions.by", { name: held.author_name });

  return (
    <li data-testid="subscription-row" className="flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <Link
          to={held.authored ? `/strategies/${held.strategy_id}` : `/strategies/explore/${held.strategy_id}`}
          className="font-display text-base font-semibold text-gain hover:text-gain-bright"
        >
          {held.strategy_name}
        </Link>
        <div className="flex flex-col gap-0.5">
          <p data-testid="subscription-origin" className="text-xs text-ink-2">
            {author}
          </p>
          <p data-testid="subscription-market" className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
            {`${held.exchange} · ${held.venue} · ${held.settlement_currency}`}
          </p>
        </div>
      </div>
      <dl className={SEAT_FIGURES_GRID}>
        <Figure icon={Calendar} label={t("strategies.subscriptions.age")} testId="subscription-age" value={age} />
        {shown !== undefined && <StrategyFigures strategy={shown} />}
        <Figure
          icon={ChartPie}
          label={t("strategies.subscriptions.share")}
          testId="subscription-share"
          value={t("strategies.subscriptions.shareValue", {
            share: readStored(held.allocation_percent) ?? held.allocation_percent,
          })}
        />
        <Figure
          icon={Gauge}
          label={t("strategies.subscriptions.leverage")}
          testId="subscription-leverage"
          value={t("strategies.subscriptions.leverageValue", { leverage: held.leverage })}
        />
      </dl>
      {held.status !== "ACTIVE" && <p className="text-sm text-ink-2">{t("strategies.subscriptions.leaving")}</p>}
    </li>
  );
}

/**
 * What the signed-in user holds, live: the strategies they trade and the ones they are leaving. A failed read
 * is an error and never an empty list, because "you hold nothing" is a claim about real money. The strategies'
 * figures come from the public list; a strategy not on it draws only the reader's own, and a failed read of it
 * says so once rather than passing for a list of private strategies.
 */
export function MySubscriptionsPage() {
  const { t } = useTranslation();
  const held = useHeldSubscriptions();
  const publics = usePublicStrategies();

  if (held.status === "pending") return <p className="text-sm text-ink-2">{t("strategies.subscriptions.loading")}</p>;
  if (held.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.subscriptions.error")}
      </p>
    );
  }
  if (held.data.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-ink-2">{t("strategies.subscriptions.empty")}</p>
        <Link to="/strategies/explore" className="text-sm text-gain hover:text-gain-bright">
          {t("strategies.subscriptions.explore")}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {publics.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.subscriptions.figuresError")}
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {held.data.map((subscription) => (
          <SubscriptionRow
            key={subscription.id}
            held={subscription}
            shown={publics.data?.find((strategy) => strategy.id === subscription.strategy_id)}
          />
        ))}
      </ul>
    </div>
  );
}
