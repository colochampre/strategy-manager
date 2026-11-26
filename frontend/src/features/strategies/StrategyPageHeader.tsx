import { Calendar } from "lucide-react";
import { createContext, type ReactNode, use } from "react";
import { useTranslation } from "react-i18next";

import { dateRange, NamedValue } from "@/features/strategies/StrategyCard";
import { Breadcrumb, type Crumb } from "@/shared/ui/PageHeader";

/**
 * The trail the page above the header draws in place of a link back: Home > Strategies > the list it came from > the
 * strategy. The pages provide it because they know the name as text; the header is drawn by a component that
 * takes the name as an element (it may be the rename field).
 */
export const StrategyCrumbs = createContext<readonly Crumb[] | null>(null);

interface StrategyPageHeaderProps {
  /** The prefix of the header's test ids: `public` on another author's page, `strategy` on the author's own. */
  prefix: string;
  /** The way back to the list the page was opened from. */
  back: ReactNode;
  /** The `h1`, or the author's title that edits it in place. */
  title: ReactNode;
  /** Whether the strategy runs, beside its name. */
  status: ReactNode;
  /** A control at the right end of the title's row, where the page has one. */
  action?: ReactNode;
  /** Who wrote it. */
  byline: string;
  /** The exchange, the venue and the settlement currency. */
  market: string;
  /** The strategy's creation: the market line dates it from there to today. */
  since: string | null;
  /** Drawn under the header's lines: the author's webhook panel. */
  children?: ReactNode;
}

/**
 * A strategy page's header, the same for the author and for anyone else (owner, 2026-11-17), so moving between the two
 * moves nothing below it: the way back, the name in a row as tall as the controls one of them carries, who wrote it,
 * and its market dated as the cards date it.
 */
export function StrategyPageHeader({
  prefix,
  back,
  title,
  status,
  action,
  byline,
  market,
  since,
  children,
}: StrategyPageHeaderProps) {
  const { t, i18n } = useTranslation();
  const dates = dateRange(since, i18n.language);
  const crumbs = use(StrategyCrumbs);

  return (
    // The title steps 6 to the page below it, whose blocks stack 4 apart (L.13).
    <header className="mb-2 flex flex-col gap-1.5">
      {crumbs === null ? back : <Breadcrumb crumbs={crumbs} />}
      <div className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1">
        {title}
        {status}
      </div>
      {/* The author and the market line on the left, the page's action at their foot on the right (`.hd-row`, ex12). */}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <p data-testid={`${prefix}-origin`} className="text-[13px] text-ink-2">
            {byline}
          </p>
          <p data-testid={`${prefix}-market`} className="flex flex-wrap items-center gap-x-1.5 font-mono text-[11px] text-ink-3">
            <span className="uppercase tracking-[0.14em]">{market}</span>
            {dates !== null && (
              <>
                <span aria-hidden="true">·</span>
                <NamedValue icon={Calendar} label={t("strategies.card.age")} testId={`${prefix}-age`}>
                  {dates}
                </NamedValue>
              </>
            )}
          </p>
        </div>
        {action}
      </div>
      {children}
    </header>
  );
}

/** The `h1` both pages draw: one size, so the name never jumps between them. */
export const STRATEGY_TITLE = "font-display text-[28px] font-semibold leading-[1.15] text-ink";
