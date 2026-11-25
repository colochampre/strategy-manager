import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ageOrder, NO_PUBLIC_FIGURES, publicFigures, seatFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { readStored } from "@/features/strategies/share-value";
import { SortControl } from "@/features/strategies/SortControl";
import { matchesName, NoMatch, StrategySearch } from "@/features/strategies/StrategySearch";
import type { CardFigures } from "@/features/strategies/StrategyCard";
import { StrategyTable, TableCard, ToolbarCard } from "@/features/strategies/StrategyTable";
import type { StrategyTableColumn, StrategyTableRow } from "@/features/strategies/StrategyTable";
import {
  aumCells,
  commonOf,
  ExchangeCell,
  NameCell,
  placementOf,
  recordCells,
  SinceCell,
  StateDot,
} from "@/features/strategies/StrategyTableCells";
import type { DotTone } from "@/features/strategies/StrategyTableCells";
import { useStrategiesPerformance } from "@/shared/api/performance";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import type { HeldSubscription, PublicStrategy } from "@/shared/api/types";

/**
 * What a seat's dot says: it is leaving, or its author's account is suspended, or the strategy runs or does not. The
 * notice of a leaving or paused seat is the dot's own tooltip (S15), so nothing it said is lost.
 */
function seatState(held: HeldSubscription, t: (key: string) => string): { tone: DotTone; label: string } {
  if (held.status !== "ACTIVE") return { tone: "off", label: t("strategies.subscriptions.leaving") };
  if (held.author_suspended) return { tone: "paused", label: t("strategies.subscriptions.paused") };
  return held.strategy_enabled
    ? { tone: "gain", label: t("strategies.detail.enabled") }
    : { tone: "off", label: t("strategies.detail.disabled") };
}

/**
 * What the signed-in user holds, live: the strategies they trade and the ones they are leaving. A failed read
 * is an error and never an empty list, because "you hold nothing" is a claim about real money. The strategies'
 * figures come from the public list; a strategy not on it draws only the reader's own, and a failed read of it
 * says so once rather than passing for a list of private strategies.
 */
export function MySubscriptionsPage() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(DEFAULT_SORT);
  return (
    <div className="flex flex-col gap-4">
      <ToolbarCard
        search={<StrategySearch value={query} onChange={setQuery} />}
        sort={<SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />}
      />
      <HeldList query={query} sort={sort} />
    </div>
  );
}

function HeldList({ query, sort }: { query: string; sort: typeof DEFAULT_SORT }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const held = useHeldSubscriptions();
  const publics = usePublicStrategies();
  // The reader's own report in each strategy, read by the list so it can order the rows by the figures they show.
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

  const locale = i18n.language;
  // A header names a currency only when every seat has it (rule 7): else each cell carries its own.
  const currency = commonOf(ordered.map(({ subscription }) => subscription.settlement_currency));
  const columns: StrategyTableColumn[] = [
    { label: t("strategies.table.head.strategy") },
    { label: t("strategies.table.head.author") },
    { label: t("strategies.table.head.exchange") },
    { label: t("strategies.table.head.since") },
    {
      label: currency === null ? t("strategies.table.head.pnlMoneyPlain") : t("strategies.table.head.pnlMoney", { currency }),
      figure: true,
    },
    { label: t("strategies.table.head.pnlPercent"), figure: true },
    { label: t("strategies.table.head.drawdown"), figure: true },
    { label: t("strategies.table.head.winRate"), figure: true },
    { label: t("strategies.table.head.subscribers"), end: true, figure: true },
    {
      label: currency === null ? t("strategies.table.head.aumPlain") : t("strategies.table.head.aum", { currency }),
      end: true,
      figure: true,
    },
    { label: t("strategies.table.head.seat"), end: true, figure: true },
  ];
  const rows: StrategyTableRow[] = ordered.map(({ subscription, card }, index) => {
    const placement = placementOf(index, ordered.length);
    const state = seatState(subscription, t);
    const author = subscription.authored
      ? t("strategies.subscriptions.yours")
      : (subscription.author_name ?? t("strategies.subscriptions.noAuthorName"));
    return {
      id: subscription.id,
      testId: "subscription-row",
      cells: [
        {
          content: (
            <NameCell
              to={subscription.authored ? `/strategies/${subscription.strategy_id}` : `/strategies/explore/${subscription.strategy_id}`}
              name={subscription.strategy_name}
              dot={<StateDot tone={state.tone} label={state.label} testId="subscription-enabled" placement={placement} />}
            />
          ),
        },
        {
          content: (
            <span data-testid="subscription-origin" className={subscription.authored ? "text-ink-3" : undefined}>
              {author}
            </span>
          ),
        },
        {
          content: (
            <ExchangeCell
              exchange={subscription.exchange}
              venue={subscription.venue}
              currency={subscription.settlement_currency}
              testId="subscription-exchange"
              placement={placement}
            />
          ),
        },
        { content: <SinceCell since={subscription.created_at} testId="subscription-age" placement={placement} /> },
        ...recordCells({
          prefix: "subscription",
          figures: card.figures,
          locale,
          pnl: { value: card.pnl, currency: subscription.settlement_currency },
          unit: currency === null,
          error: card.failed ? t("strategies.row.performanceError") : null,
        }),
        ...aumCells({ prefix: "subscription", figures: card.figures, locale, unit: currency === null }),
        {
          content: (
            <>
              <span data-testid="subscription-share">{`${readStored(subscription.allocation_percent) ?? subscription.allocation_percent}%`}</span>
              {" · "}
              <span data-testid="subscription-leverage">{t("strategies.subscriptions.leverageValue", { leverage: subscription.leverage })}</span>
            </>
          ),
        },
      ],
    };
  });

  return (
    <div className="flex flex-col gap-4">
      {publics.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.subscriptions.figuresError")}
        </p>
      )}
      <TableCard
        title={t("strategies.table.title.subscriptions")}
        headingId={headingId}
        count={t("strategies.table.subscriptionsCount", { count: rows.length })}
        countTestId="subscriptions-count"
      >
        <StrategyTable columns={columns} rows={rows} labelledBy={headingId} />
      </TableCard>
    </div>
  );
}
