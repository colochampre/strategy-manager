import { Calendar, Clock, ListChecks, Target, TrendingDown, TrendingUp, Users, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Link } from "react-router";

import { Figure, useAgeSince } from "@/features/strategies/PublicFigures";
import type { StrategyUptime } from "@/shared/api/types";
import { amountText, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";

const DAY_SECONDS = 86_400;
/** What a figure shows where there is nothing true to say yet. */
const NO_FIGURE = "—";
/** What a figure shows while its report is on its way. */
const LOADING = "…";

/**
 * The grid every card draws its figures in: four a row on a phone, with the items centred, and every figure of the
 * card on one row of equal columns from `lg`, however many the list adds (share and leverage, PnL). One grid for the
 * three lists.
 */
const CARD_GRID =
  "grid grid-cols-4 place-items-center gap-x-4 gap-y-3 sm:place-items-start lg:grid-flow-col lg:auto-cols-fr lg:gap-x-6";

/**
 * What a card shows of a strategy's record. `undefined` is a figure still being read ("…"); `null` is a figure
 * there is none of yet ("—"), such as a return with no closed trade or a strategy that is off the public list.
 */
export interface CardFigures {
  trades: number | null | undefined;
  ret: number | null | undefined;
  deepest: number | null | undefined;
  winRate: number | null | undefined;
  subscribers: { count: number; live: number } | null | undefined;
  capital: { amount: number; currency: string } | null | undefined;
}

export interface StrategyCardProps {
  /** The prefix of every test id of the card's figures (`public`, `subscription`, `strategy`). */
  prefix: string;
  rowTestId: string;
  to: string;
  name: string;
  /** Who wrote it, where that is not the reader. */
  byline?: string | null;
  archived?: boolean;
  /** Whether the strategy runs, as a word beside its name; null or absent where the card has a switch instead. */
  enabled?: boolean | null;
  market: string;
  /** The instant the age counts from: the strategy's creation, or the day the reader subscribed. */
  since: string | null;
  sinceKind: "age" | "subscribed";
  uptime: StrategyUptime;
  figures: CardFigures;
  /** Said once, in place of the figures read from the author's report, when that report failed. */
  figuresError?: string | null;
  /** Figures that vary by list, drawn after the capital in the same grid. */
  trailing?: ReactNode;
  /** The card's one control (the switch), drawn last and lifted above the stretched link. */
  action?: ReactNode;
  /** The open positions, lifted above the stretched link for their own links. */
  marks?: ReactNode;
  notice?: ReactNode;
}

/**
 * What the clock names: "Days active", the count being the value's. A baseline first activation was written by
 * the migration, so the true date is unknown and the text says "at least" (decision 9). A strategy never enabled
 * makes no claim.
 */
function uptimeText(uptime: StrategyUptime, t: TFunction): string {
  if (uptime.first_enabled_at === null) return t("strategies.card.neverEnabled");
  return t(uptime.baseline ? "strategies.card.uptimeAtLeast" : "strategies.card.uptime");
}

function uptimeValue(uptime: StrategyUptime, t: TFunction): string {
  if (uptime.first_enabled_at === null) return NO_FIGURE;
  const count = Math.floor(uptime.seconds / DAY_SECONDS);
  return uptime.baseline ? t("strategies.row.daysAtLeast", { count }) : String(count);
}

/** A ratio as a signed percentage and its tone, or the dash or the ellipsis it stands for. */
function signed(ratio: number | null | undefined, locale: string): { text: string; tone: string | undefined } {
  if (ratio === undefined) return { text: LOADING, tone: undefined };
  if (ratio === null) return { text: NO_FIGURE, tone: undefined };
  return { text: percentText(ratio, locale), tone: toneClass(ratio) };
}

/** A win rate is not a gain or a loss: unsigned, whole when it is whole, one decimal otherwise. */
function winRateText(rate: number | null | undefined, locale: string): string {
  if (rate === undefined) return LOADING;
  if (rate === null) return NO_FIGURE;
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(rate);
}

/** The word that says whether a strategy runs, beside its name: on a card and on another author's page. */
export function EnabledBadge({ enabled, testId }: { enabled: boolean; testId: string }) {
  const { t } = useTranslation();
  return (
    <span
      data-testid={testId}
      className={cn(
        "rounded-full border px-2 text-[11px] uppercase tracking-wide",
        enabled ? "border-gain text-gain" : "border-rule text-ink-3",
      )}
    >
      {t(enabled ? "strategies.detail.enabled" : "strategies.detail.disabled")}
    </span>
  );
}

/**
 * One strategy as a card, the same on Explore, on My subscriptions and on My strategies. The title link is
 * stretched over the whole card, so the card opens the strategy; the switch, the open positions and each figure's
 * icon are lifted above it and keep their own action. The keyboard meets one stop, the title.
 */
export function StrategyCard(props: StrategyCardProps) {
  const { prefix, figures, uptime } = props;
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const age = useAgeSince(props.since);
  const ret = signed(figures.ret, locale);
  const deepest = signed(figures.deepest, locale);
  const count = (value: number | null | undefined) =>
    value === undefined ? LOADING : value === null ? NO_FIGURE : String(value);

  return (
    <li
      data-testid={props.rowTestId}
      className="relative flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3 hover:bg-panel-2"
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <Link
            to={props.to}
            className="font-display text-base font-semibold text-gain after:absolute after:inset-0 hover:text-gain-bright"
          >
            {props.name}
          </Link>
          {props.archived === true && (
            <span className="text-xs uppercase tracking-wide text-ink-3">{t("strategies.row.archived")}</span>
          )}
          {props.enabled !== undefined && props.enabled !== null && (
            <EnabledBadge enabled={props.enabled} testId={`${prefix}-enabled`} />
          )}
        </div>
        {props.byline !== undefined && props.byline !== null && (
          <p data-testid={`${prefix}-origin`} className="text-xs text-ink-2">
            {props.byline}
          </p>
        )}
        <p data-testid={`${prefix}-market`} className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
          {props.market}
        </p>
      </div>
      <div className="flex items-center justify-between gap-4">
        <dl className={cn(CARD_GRID, "tabular min-w-0 grow")}>
          <Figure
            icon={Calendar}
            label={t(props.sinceKind === "age" ? "strategies.card.age" : "strategies.card.subscribed")}
            testId={`${prefix}-age`}
            value={age}
          />
          <Figure
            icon={Clock}
            label={uptimeText(uptime, t)}
            testId={`${prefix}-uptime`}
            value={uptimeValue(uptime, t)}
          />
          {props.figuresError !== undefined && props.figuresError !== null ? (
            <p role="alert" className="col-span-2 text-xs text-loss">
              {props.figuresError}
            </p>
          ) : (
            <>
              <Figure
                icon={ListChecks}
                label={t("strategies.card.trades")}
                testId={`${prefix}-trades`}
                value={count(figures.trades)}
              />
              <Figure
                icon={TrendingUp}
                label={t("strategies.card.return")}
                testId={`${prefix}-return`}
                value={ret.text}
                tone={ret.tone}
              />
              <Figure
                icon={TrendingDown}
                label={t("strategies.card.deepest")}
                testId={`${prefix}-deepest`}
                value={deepest.text}
                tone={deepest.tone}
              />
              <Figure
                icon={Target}
                label={t("strategies.card.winRate")}
                testId={`${prefix}-winrate`}
                value={winRateText(figures.winRate, locale)}
              />
            </>
          )}
          <Figure
            icon={Users}
            label={t("strategies.card.subscribers")}
            testId={`${prefix}-subscribers`}
            value={
              figures.subscribers === undefined
                ? LOADING
                : figures.subscribers === null
                  ? NO_FIGURE
                  : t("strategies.row.subscribersShort", {
                      count: figures.subscribers.count,
                      live: figures.subscribers.live,
                    })
            }
          />
          <Figure
            icon={Wallet}
            label={t("strategies.card.capital")}
            testId={`${prefix}-capital`}
            value={
              figures.capital === undefined
                ? LOADING
                : figures.capital === null
                  ? NO_FIGURE
                  : `${amountText(figures.capital.amount, figures.capital.currency, locale)} ${figures.capital.currency}`
            }
          />
          {props.trailing}
        </dl>
        {props.action !== undefined && <div className="relative z-10 shrink-0">{props.action}</div>}
      </div>
      {props.marks !== undefined && <div className="relative z-10">{props.marks}</div>}
      {props.notice}
    </li>
  );
}
