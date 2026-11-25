import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ArchivedNote } from "@/features/strategies/ArchivedToggle";
import { ageOrder, authoredFigures, sortFigure } from "@/features/strategies/card-figures";
import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import { NewStrategyDialog } from "@/features/strategies/NewStrategyDialog";
import { SortControl } from "@/features/strategies/SortControl";
import { StrategyTable, TableCard, ToolbarCard } from "@/features/strategies/StrategyTable";
import type { StrategyTableColumn, StrategyTableRow } from "@/features/strategies/StrategyTable";
import {
  aumCells,
  commonOf,
  EnableButton,
  NameCell,
  PairsCell,
  placementOf,
  recordCells,
  SinceCell,
  StateDot,
} from "@/features/strategies/StrategyTableCells";
import { matchesName, NoMatch, StrategySearch } from "@/features/strategies/StrategySearch";
import { useStrategiesPerformance } from "@/shared/api/performance";
import { usePools } from "@/shared/api/pools";
import { useStrategies } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useExchangeScope } from "@/shared/scope/exchange-store";

interface StrategyListProps {
  strategies: readonly Strategy[];
  sort: typeof DEFAULT_SORT;
  /** The note of the archived strategies, under the table. */
  footer: ReactNode;
}

/**
 * The author's strategies as a table, ordered by the figure it shows. Return is the strategy's contribution to the
 * pool, read from the very reports the table reads (one cache), so the order and the figures agree.
 */
function StrategyList({ strategies, sort, footer }: StrategyListProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const locale = i18n.language;
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

  // A header names a currency or a venue only when every row has it (rule 7): else each cell carries its own.
  const currency = commonOf(strategies.map((strategy) => strategy.settlement_currency));
  const venue = commonOf(strategies.map((strategy) => strategy.venue));
  const columns: StrategyTableColumn[] = [
    { label: t("strategies.table.head.strategy") },
    { label: venue === null ? t("strategies.table.head.pairs") : t("strategies.table.head.pairsVenue", { venue: venue.toUpperCase() }) },
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
    { label: <span className="sr-only">{t("strategies.table.head.actions")}</span>, end: true },
  ];
  const rows: StrategyTableRow[] = ordered.map(({ strategy, card }, index) => {
    const placement = placementOf(index, ordered.length);
    const archived = strategy.archived_at !== null;
    const word = t(archived ? "strategies.row.archived" : strategy.enabled ? "strategies.detail.enabled" : "strategies.detail.disabled");
    return {
      id: strategy.id,
      testId: "strategy-row",
      cells: [
        {
          content: (
            <NameCell
              to={`/strategies/${strategy.id}`}
              name={strategy.name}
              archived={archived}
              dot={
                <StateDot
                  tone={strategy.enabled && !archived ? "gain" : "off"}
                  label={word}
                  testId="strategy-enabled"
                  placement={placement}
                />
              }
            />
          ),
        },
        { content: <PairsCell pairs={strategy.allowed_pairs} testId="strategy-pairs" placement={placement} /> },
        { content: <SinceCell since={strategy.created_at} testId="strategy-age" placement={placement} /> },
        ...recordCells({
          prefix: "strategy",
          figures: card.figures,
          locale,
          pnl: { value: card.pnl, currency: strategy.settlement_currency },
          unit: currency === null,
          error: card.failed ? t("strategies.row.performanceError") : null,
        }),
        ...aumCells({ prefix: "strategy", figures: card.figures, locale, unit: currency === null }),
        { content: <EnableButton strategy={strategy} /> },
      ],
    };
  });

  return (
    <TableCard
      title={t("strategies.table.title.authored")}
      headingId={headingId}
      count={t("strategies.table.strategiesCount", { count: rows.length })}
      countTestId="strategies-count"
      footer={footer}
    >
      <StrategyTable columns={columns} rows={rows} labelledBy={headingId} />
    </TableCard>
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
 *
 * The list is read with its archived strategies, so the note under the table can say how many "Show archived" would
 * bring back; they are drawn only when the reader asks (L21).
 */
export function StrategiesPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const pools = usePools();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(DEFAULT_SORT);
  const strategies = useStrategies(true);

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
    const archivedCount = rows.filter((strategy) => strategy.archived_at !== null).length;
    const visible = includeArchived ? rows : rows.filter((strategy) => strategy.archived_at === null);
    const shown = visible.filter((strategy) => matchesName(strategy.name, query));
    const note =
      archivedCount === 0 ? undefined : (
        <ArchivedNote count={archivedCount} shown={includeArchived} onToggle={() => setIncludeArchived(!includeArchived)} />
      );
    if (shown.length > 0) {
      body = <StrategyList strategies={shown} sort={sort} footer={note} />;
    } else {
      body = (
        <div className="flex flex-col gap-4">
          {visible.length === 0 ? <p className="text-sm text-ink-3">{t("strategies.empty")}</p> : <NoMatch query={query} />}
          {note}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ToolbarCard
        search={<StrategySearch value={query} onChange={setQuery} />}
        sort={<SortControl sort={sort} onChange={(key) => setSort((current) => nextSort(current, key))} />}
        actions={
          <button
            type="button"
            disabled={exchange === null}
            onClick={() => setCreating(true)}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-gain px-4 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
          >
            <Plus aria-hidden="true" className="size-4 shrink-0" />
            {t("strategies.new.open")}
          </button>
        }
      />
      {body}
      {creating && exchange !== null && (
        <NewStrategyDialog exchange={exchange} pools={registrable} onClose={() => setCreating(false)} />
      )}
    </div>
  );
}
