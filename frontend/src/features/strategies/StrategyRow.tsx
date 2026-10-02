import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import { useStrategyPerformance } from "@/shared/api/performance";
import { useSetStrategyEnabled } from "@/shared/api/strategies";
import type { Strategy, StrategyPerformance } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";

const DAY_SECONDS = 86_400;
const DASH = "—";

interface StrategyRowProps {
  strategy: Strategy;
}

/**
 * "Active X days" with the first activation behind it (decision 9). A baseline
 * first activation was written by the migration, so the true date is unknown
 * and the text says "at least". A strategy never enabled makes no such claim.
 */
function uptimeText(strategy: Strategy, t: ReturnType<typeof useTranslation>["t"]): string {
  const { seconds, first_enabled_at: firstEnabledAt, baseline } = strategy.uptime;
  if (firstEnabledAt === null) return t("strategies.row.neverEnabled");
  const count = Math.floor(seconds / DAY_SECONDS);
  return t(baseline ? "strategies.row.activeAtLeast" : "strategies.row.active", { count });
}

interface FiguresProps {
  strategy: Strategy;
}

/**
 * Trades, all-time PnL and return, in the strategy's own pool currency; never
 * summed across strategies (rule 7). One strategy's failing report blanks only
 * its own figures and says so.
 */
function Figures({ strategy }: FiguresProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const performance = useStrategyPerformance(strategy.id);

  if (performance.status === "error") {
    return (
      <p role="alert" className="text-xs text-loss">
        {t("strategies.row.performanceError")}
      </p>
    );
  }

  const report: StrategyPerformance | null = performance.status === "success" ? performance.data : null;
  const all = report?.ranges.find((entry) => entry.range === "All");
  const pnl = all === undefined ? null : parseDecimal(all.pnl);
  const ret = all === undefined ? null : parseDecimal(all.return);
  const pending = performance.status === "pending";

  if (report !== null && all !== undefined && (pnl === null || ret === null)) {
    return (
      <p role="alert" className="text-xs text-loss">
        {t("strategies.row.performanceError")}
      </p>
    );
  }

  const empty = pending ? "…" : DASH;
  return (
    <dl className="tabular flex gap-x-5 font-mono text-xs text-ink-2">
      <div>
        <dt className="text-ink-3">{t("strategies.row.trades")}</dt>
        <dd data-testid="strategy-trades">{report === null ? empty : report.trade_count}</dd>
      </div>
      <div>
        <dt className="text-ink-3">{t("strategies.row.pnl")}</dt>
        <dd data-testid="strategy-pnl" className={cn(pnl !== null && toneClass(pnl))}>
          {pnl === null ? empty : `${amountText(pnl, strategy.settlement_currency, locale, true)} ${strategy.settlement_currency}`}
        </dd>
      </div>
      <div>
        <dt className="text-ink-3">{t("strategies.row.return")}</dt>
        <dd data-testid="strategy-return" className={cn(ret !== null && toneClass(ret))}>
          {ret === null ? empty : percentText(ret, locale)}
        </dd>
      </div>
    </dl>
  );
}

/**
 * One strategy: its name (a link to its detail), its pool, the enable switch,
 * its uptime and its figures. The switch is the only control, and a refused or
 * failed change says so in the row instead of silently snapping back.
 */
export function StrategyRow({ strategy }: StrategyRowProps) {
  const { t } = useTranslation();
  const toggle = useSetStrategyEnabled(strategy.id);
  const archived = strategy.archived_at !== null;

  return (
    <li
      data-testid="strategy-row"
      className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-md border border-rule bg-panel px-4 py-3"
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <Link
            to={`/strategies/${strategy.id}`}
            className="font-display text-base font-semibold text-gain hover:text-gain-bright"
          >
            {strategy.name}
          </Link>
          {archived && (
            <span className="text-xs uppercase tracking-wide text-ink-3">{t("strategies.row.archived")}</span>
          )}
        </div>
        <p data-testid="strategy-pool" className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
          {[strategy.venue, strategy.allowed_pairs.join(", ")].filter((part) => part !== "").join(" · ")}
        </p>
        <p data-testid="strategy-uptime" className="text-xs text-ink-2">
          {uptimeText(strategy, t)}
        </p>
      </div>
      <Figures strategy={strategy} />
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          role="switch"
          aria-checked={strategy.enabled}
          aria-label={t("strategies.row.enable", { name: strategy.name })}
          disabled={archived || toggle.isPending}
          onClick={() => toggle.mutate(!strategy.enabled)}
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-rule transition-colors disabled:opacity-50",
            strategy.enabled ? "bg-gain" : "bg-panel-2",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "inline-block size-4 rounded-full bg-ink transition-transform",
              strategy.enabled ? "translate-x-6" : "translate-x-1",
            )}
          />
        </button>
        {toggle.status === "error" && (
          <p role="alert" className="text-xs text-loss">
            {t("strategies.row.toggleError")}
          </p>
        )}
      </div>
    </li>
  );
}
