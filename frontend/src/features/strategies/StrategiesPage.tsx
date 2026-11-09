import { useState } from "react";
import type { ReactNode } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ArchivedToggle } from "@/features/strategies/ArchivedToggle";
import { ageOrder, authoredFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { NewStrategyDialog } from "@/features/strategies/NewStrategyDialog";
import { SortControl } from "@/features/strategies/SortControl";
import { StrategyRow } from "@/features/strategies/StrategyRow";
import { useStrategiesPerformance } from "@/shared/api/performance";
import { usePools } from "@/shared/api/pools";
import { useStrategies } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * The author's strategies as cards, ordered by the figure the cards show. Return is the strategy's contribution
 * to the pool, read from the very reports the cards read (one cache), so the order and the figures agree.
 */
function StrategyList({ strategies }: { strategies: readonly Strategy[] }) {
  const [sort, setSort] = useState(DEFAULT_SORT);
  const reports = useStrategiesPerformance(strategies.map((strategy) => strategy.id));
  const cards = strategies.map((strategy, index) => ({
    strategy,
    card: authoredFigures(strategy, {
      status: reports[index]?.status ?? "pending",
      data: reports[index]?.data,
    }),
  }));
  const ordered = sortCards(cards, sort, ({ strategy, card }, key) =>
    sortFigure(card.figures, ageOrder(strategy.created_at), key),
  );

  return (
    <>
      <SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />
      <ul className="flex flex-col gap-3">
        {ordered.map(({ strategy, card }) => (
          <StrategyRow key={strategy.id} strategy={strategy} card={card} />
        ))}
      </ul>
    </>
  );
}

/**
 * The Strategies container: the selected exchange's strategies, archived ones
 * only when asked, and the new-strategy dialog.
 *
 * Nothing renders until the exchange scope is KNOWN, as on the Overview: a
 * list that cannot tell which exchange it shows would claim a filter that is
 * not applied. A failed or malformed list is an error the operator can see,
 * never an empty list.
 */
export function StrategiesPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const pools = usePools();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const strategies = useStrategies(includeArchived);

  const exchange = scope.status === "ready" ? scope.exchange : null;
  const registrable =
    exchange === null || pools.data === undefined
      ? []
      : pools.data.filter((pool) => pool.exchange === exchange && pool.enabled);

  let body: ReactNode;
  if (scope.status === "loading") {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.scopeLoading")}
      </p>
    );
  } else if (scope.status === "error") {
    body = (
      <p role="alert" className="text-sm text-ink-2">
        {t("strategies.scopeError")}
      </p>
    );
  } else if (exchange === null) {
    body = <p className="text-sm text-ink-3">{t("strategies.noExchanges")}</p>;
  } else if (strategies.status === "pending") {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.loading")}
      </p>
    );
  } else if (strategies.status === "error") {
    body = (
      <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
        {t("strategies.error")}
      </p>
    );
  } else {
    const rows = strategies.data.filter((strategy) => strategy.exchange === exchange);
    body =
      rows.length === 0 ? (
        <p className="text-sm text-ink-3">{t("strategies.empty")}</p>
      ) : (
        <StrategyList strategies={rows} />
      );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
        <ArchivedToggle checked={includeArchived} onChange={setIncludeArchived} />
        <button
          type="button"
          disabled={exchange === null}
          onClick={() => setCreating(true)}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md bg-gain px-4 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        >
          <Plus aria-hidden="true" className="size-4 shrink-0" />
          {t("strategies.new.open")}
        </button>
      </div>
      {body}
      {creating && exchange !== null && (
        <NewStrategyDialog exchange={exchange} pools={registrable} onClose={() => setCreating(false)} />
      )}
    </div>
  );
}
