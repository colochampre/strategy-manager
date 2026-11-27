import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { closedLinesOf, currencyOf, exchangeChoices, openLinesOf, strategyChoices } from "@/features/trades/lines";
import { DEFAULT_PERIOD, type Period, type TradeFilters, TradesFilters } from "@/features/trades/TradesFilters";
import { TradesList } from "@/features/trades/TradesList";
import { useOpenPositions } from "@/shared/api/positions";
import { MY_TRADES_PAGE_SIZE, useMyTrades } from "@/shared/api/trades";
import { Card } from "@/shared/ui/Card";
import { CountChip } from "@/shared/ui/CountChip";
import { PageHeader } from "@/shared/ui/PageHeader";
import { PAGER_BUTTON } from "@/shared/ui/table-styles";

const DAY_MS = 24 * 3600 * 1000;

function freshFilters(): TradeFilters {
  return { period: DEFAULT_PERIOD, strategyId: "", exchange: "", anchor: Date.now() };
}

/** The instant the closed operations are asked from, or null for every one. */
function closedSince(filters: TradeFilters): string | null {
  return filters.period === "all" ? null : new Date(filters.anchor - Number(filters.period) * DAY_MS).toISOString();
}

/**
 * Every operation of the signed-in user, open and closed, from all their strategies (S5, RD.4; ex4). The open ones
 * come from the positions read and go first, newest opening first; the period does not apply to them, they are now.
 * The closed ones come from `GET /performance/trades`, newest close first. One count and one pager run over both: for
 * a page, the open ones fill it first and the closed request is cut to the rows left (L55).
 */
function MyTrades() {
  const { t } = useTranslation();
  const headingId = useId();
  const [filters, setFilters] = useState(freshFilters);
  const [page, setPage] = useState(0);
  const positions = useOpenPositions();

  const allOpen = positions.data?.positions ?? [];
  const openLines = openLinesOf(allOpen, filters.strategyId, filters.exchange);
  const start = page * MY_TRADES_PAGE_SIZE;
  const openOnPage = openLines.slice(start, start + MY_TRADES_PAGE_SIZE);
  const rest = MY_TRADES_PAGE_SIZE - openOnPage.length;
  // A page the open ones fill still asks for one closed row: the server's count and choices come with any answer.
  const trades = useMyTrades(
    {
      limit: Math.max(1, rest),
      offset: Math.max(0, start - openLines.length),
      closedSince: closedSince(filters),
      strategyId: filters.strategyId === "" ? null : filters.strategyId,
      exchange: filters.exchange === "" ? null : filters.exchange,
    },
    positions.isSuccess,
  );

  const closedTotal = trades.data?.total ?? 0;
  const count = openLines.length + closedTotal;
  const pages = Math.max(1, Math.ceil(count / MY_TRADES_PAGE_SIZE));
  // A list that shrank under the page on screen shows its last page, never an empty one.
  useEffect(() => {
    if (trades.data !== undefined && !trades.isPlaceholderData && page > pages - 1) setPage(pages - 1);
  }, [trades.data, trades.isPlaceholderData, page, pages]);

  const change = (next: Partial<Pick<TradeFilters, "period" | "strategyId" | "exchange">>) => {
    setFilters((current) => ({ ...current, ...next, anchor: next.period === undefined ? current.anchor : Date.now() }));
    setPage(0);
  };
  const clear = () => {
    setFilters(freshFilters());
    setPage(0);
  };

  const failed = positions.isError || trades.isError;
  const reading = !failed && (positions.isPending || trades.isPending || trades.isPlaceholderData);
  const lines = [...openOnPage, ...(rest > 0 && trades.data !== undefined ? closedLinesOf(trades.data.trades) : [])];
  const currencies = new Set(lines.map(currencyOf));
  const currency = currencies.size === 1 ? ([...currencies][0] ?? null) : null;

  let body;
  if (failed) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p role="alert" className="text-sm text-loss">
          {t("trades.error")}
        </p>
        <button
          type="button"
          onClick={() => {
            void positions.refetch();
            void trades.refetch();
          }}
          className="min-h-11 rounded-lg border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("trades.retry")}
        </button>
      </div>
    );
  } else if (reading) {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("trades.loading")}
      </p>
    );
  } else if (lines.length === 0) {
    body = <p className="text-sm text-ink-3">{t("trades.empty")}</p>;
  } else {
    body = (
      // The table, then the pager 6 px under it, as the closed trades lay theirs out.
      <div>
        <TradesList
          lines={lines}
          asOf={positions.data?.as_of ?? ""}
          mixed={currencies.size > 1}
          currency={currency}
          labelledBy={headingId}
        />
        <nav aria-label={t("trades.pagination")} className="mt-1.5 flex flex-wrap items-center gap-3">
          <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)} className={PAGER_BUTTON}>
            {t("trades.previous")}
          </button>
          <span className="font-mono text-xs text-ink-2">{t("trades.page", { page: page + 1, pages })}</span>
          <button type="button" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className={PAGER_BUTTON}>
            {t("trades.next")}
          </button>
        </nav>
      </div>
    );
  }

  return (
    <>
      <TradesFilters
        filters={filters}
        strategies={strategyChoices(trades.data?.strategies ?? [], allOpen)}
        exchanges={exchangeChoices(trades.data?.exchanges ?? [], allOpen)}
        onChange={change}
        onClear={clear}
      />
      <Card
        title={t("trades.title")}
        headingId={headingId}
        dense
        {...(failed || reading
          ? {}
          : { action: <CountChip testId="my-trades-count">{t("trades.count", { count })}</CountChip> })}
      >
        {body}
      </Card>
    </>
  );
}

export type { Period };

export function MyTradesPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <PageHeader crumbs={[{ label: t("nav.trades") }]} title={t("nav.trades")} subtitle={t("pageHeader.trades")} />
      <MyTrades />
    </div>
  );
}
