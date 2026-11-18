import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";

import { entryRefusal } from "@/features/strategies/entry-refusal";
import { EnabledBadge } from "@/features/strategies/StrategyCard";
import { PublicDescription } from "@/features/strategies/StrategyDescription";
import { STRATEGY_TITLE, StrategyPageHeader } from "@/features/strategies/StrategyPageHeader";
import { StrategyReportViews } from "@/features/strategies/StrategyReportViews";
import { SubscribePanel } from "@/features/strategies/SubscribePanel";
import { ApiError } from "@/shared/api/client";
import { type Entry, EntryProvider } from "@/shared/api/entry";
import { usePublicStrategy } from "@/shared/api/public-strategies";
import type { PublicStrategy } from "@/shared/api/types";

function BackToExplore() {
  const { t } = useTranslation();
  return (
    <Link to="/strategies/explore" className="font-mono text-xs text-ink-3 hover:text-ink-2">
      <span aria-hidden="true">← </span>
      {t("strategies.public.back")}
    </Link>
  );
}

function PublicRecord({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  // Two columns from lg up, as on an own strategy: the record on the left, Subscribe or the reader's seat in the
  // aside on the right. Stacked on a phone, the aside comes last.
  return (
    <div className="grid gap-9 lg:grid-cols-[minmax(0,1fr)_25rem]">
      {/* Blocks 4 apart, as on every view; the header, the description and Performance as the own page draws them. */}
      <div className="flex min-w-0 flex-col gap-4">
        <StrategyPageHeader
          prefix="public"
          back={<BackToExplore />}
          title={<h1 className={STRATEGY_TITLE}>{strategy.name}</h1>}
          status={<EnabledBadge enabled={strategy.enabled} testId="public-enabled" />}
          byline={t("strategies.public.by", { name: strategy.author_name })}
          market={`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency}`}
          since={strategy.created_at}
        />
        <PublicDescription text={strategy.description} />
        <StrategyReportViews strategy={strategy} />
      </div>
      <SubscribePanel strategy={strategy} />
    </div>
  );
}

/**
 * One public strategy, for anyone signed in. A 404 is an ordinary answer here, not a fault: a strategy turned
 * private, archived or never public reads the same, so the page says only that it is not on the list. The one
 * exception is the backend's: a strategy turned private still answers a reader who holds a live seat on it, since
 * this page is where that seat is managed (tasks.md J.1).
 *
 * A 404 wins over what was read before it: once that seat is left, the refetch answers 404 while the query keeps
 * its old data, and drawing that data would offer a Subscribe the API refuses.
 */
export function PublicStrategyPage() {
  const [search] = useSearchParams();
  const entry = useMemo(() => entryOf(search), [search]);
  return (
    <EntryProvider value={entry}>
      <PublicStrategyRead entry={entry} />
    </EntryProvider>
  );
}

/** The link or the code the page's address carries; an empty one is none. */
function entryOf(search: URLSearchParams): Entry {
  const link = search.get("link") ?? "";
  const code = search.get("code") ?? "";
  return { ...(link === "" ? {} : { link }), ...(code === "" ? {} : { code }) };
}

/**
 * A refusal the link or the code earned (a dead code, too many wrong codes, a link or a code that opens nothing)
 * reads like the 404: in words, with nothing drawn from before it.
 */
function PublicStrategyRead({ entry }: { entry: Entry }) {
  const { t } = useTranslation();
  const { strategyId = "" } = useParams();
  const strategy = usePublicStrategy(strategyId);

  const refused = entryRefusal(strategy.error, entry);
  const gone = refused === null && strategy.error instanceof ApiError && strategy.error.status === 404;
  if (strategy.data !== undefined && !gone && refused === null) return <PublicRecord strategy={strategy.data} />;

  return (
    <div className="flex flex-col items-start gap-4">
      <BackToExplore />
      {strategy.status === "pending" && <p className="text-sm text-ink-2">{t("strategies.public.loading")}</p>}
      {gone && <p className="text-sm text-ink-2">{t("strategies.public.notFound")}</p>}
      {refused !== null && <p className="text-sm text-ink-2">{t(refused)}</p>}
      {strategy.status === "error" && !gone && refused === null && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.public.error")}
        </p>
      )}
    </div>
  );
}
