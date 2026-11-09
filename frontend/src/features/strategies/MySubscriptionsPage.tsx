import { ChartPie, Gauge } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { OpenMarks } from "@/features/positions/OpenMarks";
import { ageOrder, NO_PUBLIC_FIGURES, publicFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { Figure } from "@/features/strategies/PublicFigures";
import { readStored } from "@/features/strategies/share-value";
import { SortControl } from "@/features/strategies/SortControl";
import { StrategyCard } from "@/features/strategies/StrategyCard";
import type { CardFigures } from "@/features/strategies/StrategyCard";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import type { HeldSubscription, PublicStrategy } from "@/shared/api/types";

/** What a card shows while the public list is on its way: every public figure is being read. */
const READING_FIGURES: CardFigures = {
  trades: undefined,
  ret: undefined,
  deepest: undefined,
  winRate: undefined,
  subscribers: undefined,
  capital: undefined,
};

interface SubscriptionCardProps {
  held: HeldSubscription;
  figures: CardFigures;
}

/**
 * One seat, as Explore draws its strategy: the same card, with the reader's time in it in place of the strategy's
 * age, then the share of the pool and the leverage, and the reader's own open positions under it. It is a summary:
 * the seat is changed and left on the strategy's own page, which the whole card opens.
 */
function SubscriptionCard({ held, figures }: SubscriptionCardProps) {
  const { t } = useTranslation();
  const author = held.authored
    ? t("strategies.subscriptions.yours")
    : held.author_name === null
      ? t("strategies.subscriptions.noAuthorName")
      : t("strategies.subscriptions.by", { name: held.author_name });

  return (
    <StrategyCard
      prefix="subscription"
      rowTestId="subscription-row"
      to={held.authored ? `/strategies/${held.strategy_id}` : `/strategies/explore/${held.strategy_id}`}
      name={held.strategy_name}
      byline={author}
      enabled={held.strategy_enabled}
      market={`${held.exchange} · ${held.venue} · ${held.settlement_currency}`}
      since={held.created_at}
      sinceKind="subscribed"
      uptime={held.strategy_uptime}
      figures={figures}
      trailing={
        <>
          <Figure
            icon={ChartPie}
            label={t("strategies.card.share")}
            testId="subscription-share"
            value={t("strategies.subscriptions.shareValue", {
              share: readStored(held.allocation_percent) ?? held.allocation_percent,
            })}
          />
          <Figure
            icon={Gauge}
            label={t("strategies.card.leverage")}
            testId="subscription-leverage"
            value={t("strategies.subscriptions.leverageValue", { leverage: held.leverage })}
          />
        </>
      }
      marks={<OpenMarks strategy={{ id: held.strategy_id, name: held.strategy_name, exchange: held.exchange }} />}
      notice={held.status !== "ACTIVE" ? <p className="text-sm text-ink-2">{t("strategies.subscriptions.leaving")}</p> : undefined}
    />
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
  const [sort, setSort] = useState(DEFAULT_SORT);

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

  const figuresOf = (subscription: HeldSubscription): CardFigures => {
    if (publics.status === "pending") return READING_FIGURES;
    const shown: PublicStrategy | undefined = publics.data?.find((strategy) => strategy.id === subscription.strategy_id);
    return shown === undefined ? NO_PUBLIC_FIGURES : publicFigures(shown);
  };
  const ordered = sortCards(held.data, sort, (subscription, key) =>
    sortFigure(figuresOf(subscription), ageOrder(subscription.created_at), key),
  );

  return (
    <div className="flex flex-col gap-3">
      {publics.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.subscriptions.figuresError")}
        </p>
      )}
      <SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />
      <ul className="flex flex-col gap-3">
        {ordered.map((subscription) => (
          <SubscriptionCard key={subscription.id} held={subscription} figures={figuresOf(subscription)} />
        ))}
      </ul>
    </div>
  );
}
