import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ageOrder, publicFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { CodeEntry } from "@/features/strategies/CodeEntry";
import { SortControl } from "@/features/strategies/SortControl";
import { StrategyCard } from "@/features/strategies/StrategyCard";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import type { PublicStrategy } from "@/shared/api/types";

function PublicStrategyCard({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  return (
    <StrategyCard
      prefix="public"
      rowTestId="public-strategy-row"
      to={`/strategies/explore/${strategy.id}`}
      name={strategy.name}
      byline={t("strategies.public.by", { name: strategy.author_name })}
      enabled={strategy.enabled}
      market={`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency}`}
      since={strategy.created_at}
      sinceKind="age"
      uptime={strategy.uptime}
      figures={publicFigures(strategy)}
    />
  );
}

/**
 * Every public strategy, for anyone signed in: a user with no key browses it the same (decision 13). Under the
 * server's brake nobody trades live, so the figures carry no capital; the header's (i) says why. "I have a code" sits
 * above the list whatever its state, since a strategy shared by a code is on no list.
 */
export function ExplorePage() {
  return (
    <div className="flex flex-col gap-4">
      <CodeEntry />
      <PublicList />
    </div>
  );
}

function PublicList() {
  const { t } = useTranslation();
  const strategies = usePublicStrategies();
  const [sort, setSort] = useState(DEFAULT_SORT);

  if (strategies.status === "pending") return <p className="text-sm text-ink-2">{t("strategies.explore.loading")}</p>;
  if (strategies.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.explore.error")}
      </p>
    );
  }
  if (strategies.data.length === 0) return <p className="text-sm text-ink-2">{t("strategies.explore.empty")}</p>;

  const ordered = sortCards(strategies.data, sort, (strategy, key) =>
    sortFigure(publicFigures(strategy), ageOrder(strategy.created_at), key),
  );

  return (
    <>
      <SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />
      <ul className="flex flex-col gap-4">
        {ordered.map((strategy) => (
          <PublicStrategyCard key={strategy.id} strategy={strategy} />
        ))}
      </ul>
    </>
  );
}
