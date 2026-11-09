import { Calendar, Clock, Coins, ListChecks, TrendingDown, TrendingUp, Trophy, Users, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Link } from "react-router";

import { Figure, useAgeSince } from "@/features/strategies/PublicFigures";
import type { StrategyUptime } from "@/shared/api/types";
import { amountText, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { Tooltip } from "@/shared/ui/Tooltip";

const DAY_SECONDS = 86_400;
/** What a figure shows where there is nothing true to say yet. */
const NO_FIGURE = "—";
/** What a figure shows while its report is on its way. */
const LOADING = "…";

/**
 * The grid every card draws its figures in: four a row on a phone, with the items centred, and every figure of the
 * card on one row from `lg`, however many the list adds (share and leverage, PnL), spread as another author's page
 * spreads them: each column as wide as its value, the first at the card's left edge and the last at its right, the
 * room left shared out equally between them, so a long PnL takes no room from its neighbours. The phone's four
 * columns are dropped there: kept, the first four would stay `minmax(0, 1fr)`. One grid for the three lists.
 */
const CARD_GRID =
  "grid grid-cols-4 place-items-center gap-x-4 gap-y-3 sm:place-items-start lg:grid-flow-col lg:grid-cols-none lg:auto-cols-max lg:justify-between lg:gap-x-6";

/**
 * The same figures on a strategy's page, whose column is narrower than a card and shares the screen with an aside:
 * one row wherever the column itself holds eight figures (a container query, 32rem), each as wide as its own value
 * and the gaps shared out between them; four a row where it does not.
 */
const PAGE_GRID =
  "grid grid-cols-4 place-items-center gap-x-4 gap-y-3 sm:place-items-start @[32rem]:grid-flow-col @[32rem]:grid-cols-none @[32rem]:auto-cols-max @[32rem]:justify-between";

/**
 * What a card shows of a strategy's record. `undefined` is a figure still being read ("…"); `null` is a figure
 * there is none of yet ("—"), such as a return with no closed trade or a strategy that is off the public list.
 */
export interface CardFigures {
  trades: number | null | undefined;
  ret: number | null | undefined;
  deepest: number | null | undefined;
  winRate: number | null | undefined;
  /** Those trading it live: one number, the tooltip says live. */
  subscribers: number | null | undefined;
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
  /** A PnL, drawn left of the return, where the card has one: the author's, or the reader's own in a seat. */
  pnl?: CardPnl;
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

/**
 * The word that says whether a strategy runs, beside its name on a strategy's page: the author's own and another
 * author's draw the same mark. An archived strategy says so instead, in the quiet colour.
 */
export function EnabledBadge({ enabled, archived = false, testId }: { enabled: boolean; archived?: boolean; testId: string }) {
  const { t } = useTranslation();
  const status = archived ? "strategies.row.archived" : enabled ? "strategies.detail.enabled" : "strategies.detail.disabled";
  return (
    <span
      data-testid={testId}
      className={cn(
        "rounded border px-2 py-1 font-mono text-[11px] uppercase tracking-[0.12em]",
        enabled && !archived ? "border-gain text-gain" : "border-rule text-ink-3",
      )}
    >
      {t(status)}
    </span>
  );
}

/**
 * Whether a strategy runs, on a card: a filled dot beside its name, where a word on every card repeated itself. Green
 * when it runs; grey when it does not, never the loss colour, since a stopped strategy is not a fault. The word is the
 * dot's name and its tooltip, and the dot is lifted above the card's stretched link so the tooltip answers.
 */
export function EnabledDot({ enabled, testId }: { enabled: boolean; testId: string }) {
  const { t } = useTranslation();
  const word = t(enabled ? "strategies.detail.enabled" : "strategies.detail.disabled");
  return (
    <Tooltip text={word} className="relative z-10">
      <span
        role="img"
        aria-label={word}
        data-testid={testId}
        className={cn("block size-2.5 rounded-full", enabled ? "bg-gain" : "bg-ink-3")}
      />
    </Tooltip>
  );
}

/** A PnL a card or a page draws: money in its currency, `undefined` while read, `null` where there is none. */
export interface CardPnl {
  value: number | null | undefined;
  currency: string;
  /** The tooltip, where "PnL" alone would not say whose or over what range. */
  label?: string;
  /** Added to the figure's classes: where it is drawn, by the width it has. */
  className?: string;
}

interface CardFigureGridProps {
  /** The prefix of every figure's test id. */
  prefix: string;
  since: string | null;
  sinceKind: "age" | "subscribed";
  uptime: StrategyUptime;
  figures: CardFigures;
  figuresError?: string | null | undefined;
  pnl?: CardPnl | undefined;
  trailing?: ReactNode;
  /** The grid's own test id, where a page names the row. */
  testId?: string;
  /** Replaces the return's tooltip, for a return that follows a range. */
  returnLabel?: string;
  /** An information button beside the return's icon. */
  returnInfo?: ReactNode;
  /** An information button beside the capital's icon. */
  capitalInfo?: ReactNode;
  /** A card's grid, or a page's (one row where its column holds it). */
  layout?: "card" | "page";
  className?: string;
}

/**
 * A strategy's figures as the cards draw them: age, days active, closed trades, a PnL where there is one, return,
 * deepest fall, win rate, live subscribers and capital, each an icon over its value. A card draws it, and so does another author's page, under
 * Performance, where the return and the fall follow the chart's range.
 */
export function CardFigureGrid({
  prefix,
  since,
  sinceKind,
  uptime,
  figures,
  figuresError,
  pnl,
  trailing,
  testId,
  returnLabel,
  returnInfo,
  capitalInfo,
  layout = "card",
  className,
}: CardFigureGridProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const age = useAgeSince(since);
  const ret = signed(figures.ret, locale);
  const deepest = signed(figures.deepest, locale);
  const count = (value: number | null | undefined) =>
    value === undefined ? LOADING : value === null ? NO_FIGURE : String(value);

  return (
    <dl data-testid={testId} className={cn(layout === "page" ? PAGE_GRID : CARD_GRID, "tabular", className)}>
      <Figure
        icon={Calendar}
        label={t(sinceKind === "age" ? "strategies.card.age" : "strategies.card.subscribed")}
        testId={`${prefix}-age`}
        value={age}
      />
      <Figure
        icon={Clock}
        label={uptimeText(uptime, t)}
        testId={`${prefix}-uptime`}
        value={uptimeValue(uptime, t)}
      />
      {figuresError !== undefined && figuresError !== null ? (
        <p role="alert" className="col-span-2 text-xs text-loss">
          {figuresError}
        </p>
      ) : (
        <>
          <Figure
            icon={ListChecks}
            label={t("strategies.card.trades")}
            testId={`${prefix}-trades`}
            value={count(figures.trades)}
          />
          {pnl !== undefined && (
            <Figure
              icon={Coins}
              label={pnl.label ?? t("strategies.card.pnl")}
              testId={`${prefix}-pnl`}
              value={
                pnl.value === undefined
                  ? LOADING
                  : pnl.value === null
                    ? NO_FIGURE
                    : `${amountText(pnl.value, pnl.currency, locale, true)} ${pnl.currency}`
              }
              tone={pnl.value === undefined || pnl.value === null ? undefined : toneClass(pnl.value)}
              className={pnl.className}
            />
          )}
          <Figure
            icon={TrendingUp}
            label={returnLabel ?? t("strategies.card.return")}
            testId={`${prefix}-return`}
            value={ret.text}
            tone={ret.tone}
            info={returnInfo}
          />
          <Figure
            icon={TrendingDown}
            label={t("strategies.card.deepest")}
            testId={`${prefix}-deepest`}
            value={deepest.text}
            tone={deepest.tone}
          />
          <Figure
            icon={Trophy}
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
        value={count(figures.subscribers)}
      />
      <Figure
        icon={Wallet}
        label={t("strategies.card.capital")}
        testId={`${prefix}-capital`}
        info={capitalInfo}
        value={
          figures.capital === undefined
            ? LOADING
            : figures.capital === null
              ? NO_FIGURE
              : `${amountText(figures.capital.amount, figures.capital.currency, locale)} ${figures.capital.currency}`
        }
      />
      {trailing}
    </dl>
  );
}

/**
 * One strategy as a card, the same on Explore, on My subscriptions and on My strategies. The title link is
 * stretched over the whole card, so the card opens the strategy; the switch, the open positions and each figure's
 * icon are lifted above it and keep their own action. The keyboard meets one stop, the title.
 */
export function StrategyCard(props: StrategyCardProps) {
  const { prefix, figures, uptime } = props;
  const { t } = useTranslation();

  return (
    <li
      data-testid={props.rowTestId}
      className="relative flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3 hover:bg-panel-2"
    >
      {/* The card's one control sits on the title's line, at its right end, so the figures have the card's width. */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2">
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
              <EnabledDot enabled={props.enabled} testId={`${prefix}-enabled`} />
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
        {props.action !== undefined && <div className="relative z-10 shrink-0">{props.action}</div>}
      </div>
      <CardFigureGrid
        prefix={prefix}
        since={props.since}
        sinceKind={props.sinceKind}
        uptime={uptime}
        figures={figures}
        figuresError={props.figuresError}
        pnl={props.pnl}
        trailing={props.trailing}
        className="min-w-0"
      />
      {props.marks !== undefined && <div className="relative z-10">{props.marks}</div>}
      {props.notice}
    </li>
  );
}
