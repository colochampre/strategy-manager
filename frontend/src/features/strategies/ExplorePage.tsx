import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ageOrder, publicFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { CodeEntry } from "@/features/strategies/CodeEntry";
import { SortControl } from "@/features/strategies/SortControl";
import { matchesName, NoMatch, StrategySearch } from "@/features/strategies/StrategySearch";
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
import { usePublicStrategies } from "@/shared/api/public-strategies";

/**
 * Every public strategy, for anyone signed in: a user with no key browses it the same (decision 13). Under the
 * server's brake nobody trades live, so the figures carry no capital; the header's (i) says why. "I have a code" sits
 * above the list whatever its state, since a strategy shared by a code is on no list.
 */
export function ExplorePage() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(DEFAULT_SORT);
  return (
    <div className="flex flex-col gap-4">
      <ToolbarCard
        search={<StrategySearch value={query} onChange={setQuery} />}
        actions={<CodeEntry />}
        sort={<SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />}
      />
      <PublicList query={query} sort={sort} />
    </div>
  );
}

function PublicList({ query, sort }: { query: string; sort: typeof DEFAULT_SORT }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const strategies = usePublicStrategies();

  if (strategies.status === "pending") return <p className="text-sm text-ink-2">{t("strategies.explore.loading")}</p>;
  if (strategies.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.explore.error")}
      </p>
    );
  }
  if (strategies.data.length === 0) return <p className="text-sm text-ink-2">{t("strategies.explore.empty")}</p>;
  const shown = strategies.data.filter((strategy) => matchesName(strategy.name, query));
  if (shown.length === 0) return <NoMatch query={query} />;

  const ordered = sortCards(shown, sort, (strategy, key) =>
    sortFigure(publicFigures(strategy), ageOrder(strategy.created_at), key),
  );

  const locale = i18n.language;
  // A header names a currency only when every strategy has it (rule 7): else each cell carries its own.
  const currency = commonOf(ordered.map((strategy) => strategy.settlement_currency));
  const columns: StrategyTableColumn[] = [
    { label: t("strategies.table.head.strategy") },
    { label: t("strategies.table.head.author") },
    { label: t("strategies.table.head.exchange") },
    { label: t("strategies.table.head.since") },
    { label: t("strategies.table.head.pnlPercent"), figure: true },
    { label: t("strategies.table.head.drawdown"), figure: true },
    { label: t("strategies.table.head.winRate"), figure: true },
    { label: t("strategies.table.head.subscribers"), end: true, figure: true },
    {
      label: currency === null ? t("strategies.table.head.aumPlain") : t("strategies.table.head.aum", { currency }),
      end: true,
      figure: true,
    },
  ];
  const rows: StrategyTableRow[] = ordered.map((strategy, index) => {
    const placement = placementOf(index, ordered.length);
    const figures = publicFigures(strategy);
    return {
      id: strategy.id,
      testId: "public-strategy-row",
      cells: [
        {
          content: (
            <NameCell
              to={`/strategies/explore/${strategy.id}`}
              name={strategy.name}
              dot={
                <StateDot
                  tone={strategy.enabled ? "gain" : "off"}
                  label={t(strategy.enabled ? "strategies.detail.enabled" : "strategies.detail.disabled")}
                  testId="public-enabled"
                  placement={placement}
                />
              }
            />
          ),
        },
        { content: <span data-testid="public-origin">{strategy.author_name}</span> },
        {
          content: (
            <ExchangeCell
              exchange={strategy.exchange}
              venue={strategy.venue}
              currency={strategy.settlement_currency}
              testId="public-exchange"
              placement={placement}
            />
          ),
        },
        { content: <SinceCell since={strategy.created_at} testId="public-age" placement={placement} /> },
        // The public record carries no money: another author's PnL is theirs alone, so only the return is drawn.
        ...recordCells({ prefix: "public", figures, locale, unit: currency === null }),
        ...aumCells({ prefix: "public", figures, locale, unit: currency === null }),
      ],
    };
  });

  return (
    <TableCard
      title={t("strategies.table.title.explore")}
      headingId={headingId}
      count={t("strategies.table.strategiesCount", { count: rows.length })}
      countTestId="public-strategies-count"
    >
      <StrategyTable columns={columns} rows={rows} labelledBy={headingId} roomy />
    </TableCard>
  );
}
