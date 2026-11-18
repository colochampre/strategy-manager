import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { OpenMarks } from "@/features/positions/OpenMarks";
import { ageOrder, NO_PUBLIC_FIGURES, publicFigures, seatFigures, sortFigure } from "@/features/strategies/card-figures";
import type { AuthoredCard } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { readStored } from "@/features/strategies/share-value";
import { SortControl } from "@/features/strategies/SortControl";
import { ListToolbar, matchesName, NoMatch, StrategySearch } from "@/features/strategies/StrategySearch";
import { StrategyCard } from "@/features/strategies/StrategyCard";
import type { CardFigures } from "@/features/strategies/StrategyCard";
import { useStrategiesPerformance } from "@/shared/api/performance";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import type { HeldSubscription, PublicStrategy } from "@/shared/api/types";

interface SubscriptionCardProps {
  held: HeldSubscription;
  /** The reader's own record in the strategy, with its live subscribers and capital from the public list. */
  card: AuthoredCard;
}

/**
 * One seat, as Explore draws its strategy: the same card, dated from the day the reader subscribed, with the
 * reader's own record (owner, 2026-11-17: the PnL and the return beside it speak of the same money), then the
 * strategy's live subscribers and capital, the seat's share and leverage, and the reader's own open positions under
 * it. It is a summary: the seat is changed and left on the strategy's own page, which the whole card opens.
 */
function SubscriptionCard({ held, card }: SubscriptionCardProps) {
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
      figures={card.figures}
      figuresError={card.failed ? t("strategies.row.performanceError") : null}
      pnl={{ value: card.pnl, currency: held.settlement_currency }}
      setup={{
        // The card adds the percent sign, as a smaller unit.
        share: readStored(held.allocation_percent) ?? held.allocation_percent,
        leverage: t("strategies.subscriptions.leverageValue", { leverage: held.leverage }),
      }}
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
  const [query, setQuery] = useState("");
  return (
    <div className="flex flex-col gap-4">
      <ListToolbar search={<StrategySearch value={query} onChange={setQuery} />} />
      <HeldList query={query} />
    </div>
  );
}

function HeldList({ query }: { query: string }) {
  const { t } = useTranslation();
  const held = useHeldSubscriptions();
  const publics = usePublicStrategies();
  const [sort, setSort] = useState(DEFAULT_SORT);
  // The reader's own report in each strategy, read by the list so it can order the cards by the figures they show.
  const seats = held.data ?? [];
  const reports = useStrategiesPerformance(seats.map((subscription) => subscription.strategy_id));

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

  /** Who trades the strategy live and with how much: the public list's, the dash where it is off the list. */
  const aumOf = (subscription: HeldSubscription): Pick<CardFigures, "subscribers" | "capital"> => {
    if (publics.status === "pending") return { subscribers: undefined, capital: undefined };
    const listed: PublicStrategy | undefined = publics.data?.find((strategy) => strategy.id === subscription.strategy_id);
    const figures = listed === undefined ? NO_PUBLIC_FIGURES : publicFigures(listed);
    return { subscribers: figures.subscribers, capital: figures.capital };
  };
  const cards = held.data.map((subscription, index) => ({
    subscription,
    card: seatFigures(
      { status: reports[index]?.status ?? "pending", data: reports[index]?.data },
      aumOf(subscription),
    ),
  }));
  const shown = cards.filter(({ subscription }) => matchesName(subscription.strategy_name, query));
  if (shown.length === 0) return <NoMatch query={query} />;
  const ordered = sortCards(shown, sort, ({ subscription, card }, key) =>
    sortFigure(card.figures, ageOrder(subscription.created_at), key),
  );

  return (
    <div className="flex flex-col gap-4">
      {publics.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.subscriptions.figuresError")}
        </p>
      )}
      <SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />
      <ul className="flex flex-col gap-4">
        {ordered.map(({ subscription, card }) => (
          <SubscriptionCard key={subscription.id} held={subscription} card={card} />
        ))}
      </ul>
    </div>
  );
}
