import { Calendar, ChartPie, Coins, Gauge, SlidersHorizontal, TrendingDown, Trophy, Users, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { amountText, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { Tooltip } from "@/shared/ui/Tooltip";

/** What a figure shows where there is nothing true to say yet. */
const NO_FIGURE = "—";
/** What a figure shows while its report is on its way. */
const LOADING = "…";

/**
 * What a card shows of a strategy's record. `undefined` is a figure still being read ("…"); `null` is a figure
 * there is none of yet ("—"), such as a return with no closed trade or a strategy that is off the public list.
 */
export interface CardFigures {
  trades: number | null | undefined;
  ret: number | null | undefined;
  deepest: number | null | undefined;
  winRate: number | null | undefined;
  /** The trades won out of the trades closed, where a card says both; absent where nothing draws it (a page's row). */
  profitable?: { wins: number; closed: number } | null | undefined;
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
  /** The instant the dates on the market line run from: the strategy's creation, or the day the reader subscribed. */
  since: string | null;
  sinceKind: "age" | "subscribed";
  figures: CardFigures;
  /** Said once, in place of the figures read from a report, when that report failed. */
  figuresError?: string | null;
  /** A PnL, drawn before the return under Total PnL, where the card has one: the author's, or the reader's own. */
  pnl?: CardPnl;
  /** A seat's share of the pool and leverage, as written: only My subscriptions draws them. */
  setup?: { share: string; leverage: string };
  /** The card's one control (the switch), drawn last and lifted above the stretched link. */
  action?: ReactNode;
  /** The open positions, lifted above the stretched link for their own links. */
  marks?: ReactNode;
  notice?: ReactNode;
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
}

/**
 * The card's figures in five columns from `lg`, each as wide as the next, as TradingView's strategy tester lays out
 * its key stats; two a row on a phone, three from `sm`.
 */
export const STATS_GRID =
  "grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-flow-col lg:grid-cols-none lg:auto-cols-fr lg:gap-x-6";

const DATE_OPTIONS: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };

/** "Oct 12, 2026 – Nov 17, 2026": from `since` to today, in UTC; null where `since` cannot be read. */
export function dateRange(since: string | null, locale: string): string | null {
  const from = since === null ? Number.NaN : Date.parse(since);
  if (Number.isNaN(from)) return null;
  const format = new Intl.DateTimeFormat(locale, DATE_OPTIONS);
  return `${format.format(new Date(from))} – ${format.format(new Date())}`;
}

/**
 * A value with the icon that names it, under one tooltip: the pointer on the icon or on the value shows it (owner,
 * 2026-11-17). Lifted above the card's stretched link so it answers.
 */
export function NamedValue({
  icon: Icon,
  label,
  testId,
  children,
}: {
  icon: typeof Users;
  label: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <Tooltip text={label} describes={false} className="relative z-10 inline-flex items-center gap-1">
      <Icon role="img" aria-label={label} className="size-3.5 shrink-0 text-ink-3" />
      <span data-testid={testId}>{children}</span>
    </Tooltip>
  );
}

/** A unit joined to its number and drawn smaller, so the figure leads (owner, 2026-11-17): `+1,738.16USDT`, `+12.5%`. */
function Unit({ children }: { children: string }) {
  return <span className="text-[0.75em]">{children}</span>;
}

/** Money with its currency as a smaller unit, or the ellipsis or the dash it stands for. */
export function money(amount: number | null | undefined, currency: string, locale: string, signedAmount = false): ReactNode {
  if (amount === undefined) return LOADING;
  if (amount === null) return NO_FIGURE;
  return (
    <>
      {amountText(amount, currency, locale, signedAmount)}
      <Unit>{currency}</Unit>
    </>
  );
}

/** A signed ratio as a percentage with a smaller sign and its tone, or the ellipsis or the dash it stands for. */
export function percent(ratio: number | null | undefined, locale: string): { value: ReactNode; tone: string | undefined } {
  if (ratio === undefined) return { value: LOADING, tone: undefined };
  if (ratio === null) return { value: NO_FIGURE, tone: undefined };
  return {
    value: (
      <>
        {percentText(ratio, locale, false)}
        <Unit>%</Unit>
      </>
    ),
    tone: toneClass(ratio),
  };
}

/** A win rate, unsigned, whole when it is whole and one decimal otherwise, with a smaller sign. */
function rate(value: number | null | undefined, locale: string): ReactNode {
  if (value === undefined) return LOADING;
  if (value === null) return NO_FIGURE;
  return (
    <>
      {new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value * 100)}
      <Unit>%</Unit>
    </>
  );
}

/** One labelled group of the card: an icon and a label, the values beneath on one line. */
export function StatGroup({
  testId,
  icon: Icon,
  label,
  hint,
  info,
  children,
}: {
  testId: string;
  icon: typeof Users;
  label: string;
  /** What the label means, on hover, for a term not everyone knows. */
  hint?: string;
  /** An information button after the label, on a page that explains the figure in a text beneath. */
  info?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col gap-1">
      <dt className="flex items-center gap-1.5 text-xs text-ink-3">
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        {hint === undefined ? (
          <span>{label}</span>
        ) : (
          <Tooltip text={hint} className="relative z-10 inline-flex cursor-help underline decoration-dotted underline-offset-2">
            <span>{label}</span>
          </Tooltip>
        )}
        {info}
      </dt>
      <dd className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-sm tabular-nums text-ink">{children}</dd>
    </div>
  );
}

interface FigureGroupsProps {
  /** The prefix of every value's test id. */
  prefix: string;
  figures: CardFigures;
  figuresError?: string | null | undefined;
  pnl?: CardPnl | undefined;
  setup?: { share: string; leverage: string } | undefined;
  /** The row's own test id, where a page names it. */
  testId?: string;
  /** Replaces "Total PnL", for a page whose PnL and return follow the chart's range. */
  pnlLabel?: string;
  /** An information button after the Total PnL label, about the return. */
  pnlInfo?: ReactNode;
  /** An information button after the AuM label, about the capital. */
  aumInfo?: ReactNode;
}

/**
 * A strategy's figures under one label per group (owner, 2026-11-17, after TradingView's strategy tester): Total PnL
 * (the PnL where there is one, and the return), Max drawdown, Profitable trades (the rate, and the wins out of the
 * trades closed), AuM (who trades it live, and with how much) and, on a seat's card, its settings. Every card draws
 * it, and so does every strategy's page, under Performance.
 */
export function FigureGroups({
  prefix,
  figures,
  figuresError,
  pnl,
  setup,
  testId,
  pnlLabel,
  pnlInfo,
  aumInfo,
}: FigureGroupsProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const ret = percent(figures.ret, locale);
  const deepest = percent(figures.deepest, locale);
  const count = (value: number | null | undefined) =>
    value === undefined ? LOADING : value === null ? NO_FIGURE : String(value);

  return (
    <dl data-testid={testId} className={cn(STATS_GRID, "min-w-0")}>
      {figuresError !== undefined && figuresError !== null ? (
        <p role="alert" className="col-span-2 text-xs text-loss">
          {figuresError}
        </p>
      ) : (
        <>
          <StatGroup
            testId={`${prefix}-group-pnl`}
            icon={Coins}
            label={pnlLabel ?? t("strategies.card.totalPnl")}
            info={pnlInfo}
          >
            {pnl !== undefined && (
              <span
                data-testid={`${prefix}-pnl`}
                className={pnl.value === undefined || pnl.value === null ? undefined : toneClass(pnl.value)}
              >
                {money(pnl.value, pnl.currency, locale, true)}
              </span>
            )}
            <span data-testid={`${prefix}-return`} className={ret.tone}>
              {ret.value}
            </span>
          </StatGroup>
          <StatGroup testId={`${prefix}-group-drawdown`} icon={TrendingDown} label={t("strategies.card.maxDrawdown")}>
            <span data-testid={`${prefix}-deepest`} className={deepest.tone}>
              {deepest.value}
            </span>
          </StatGroup>
          <StatGroup testId={`${prefix}-group-profitable`} icon={Trophy} label={t("strategies.card.winRate")}>
            <span data-testid={`${prefix}-winrate`}>{rate(figures.winRate, locale)}</span>
            {figures.profitable !== undefined && figures.profitable !== null && (
              <span data-testid={`${prefix}-wins`} className="text-ink-2">
                {`${figures.profitable.wins}/${figures.profitable.closed}`}
              </span>
            )}
          </StatGroup>
        </>
      )}
      <StatGroup
        testId={`${prefix}-group-aum`}
        icon={Wallet}
        label={t("strategies.card.aum")}
        hint={t("strategies.card.aumHint")}
        info={aumInfo}
      >
        <NamedValue icon={Users} label={t("strategies.card.subscribers")} testId={`${prefix}-subscribers`}>
          {count(figures.subscribers)}
        </NamedValue>
        <span data-testid={`${prefix}-capital`}>
          {figures.capital === null || figures.capital === undefined
            ? money(figures.capital, "", locale)
            : money(figures.capital.amount, figures.capital.currency, locale)}
        </span>
      </StatGroup>
      {setup !== undefined && (
        <StatGroup testId={`${prefix}-group-setup`} icon={SlidersHorizontal} label={t("strategies.card.setup")}>
          <NamedValue icon={ChartPie} label={t("strategies.card.share")} testId={`${prefix}-share`}>
            {setup.share}
            <Unit>%</Unit>
          </NamedValue>
          <NamedValue icon={Gauge} label={t("strategies.card.leverage")} testId={`${prefix}-leverage`}>
            {setup.leverage}
          </NamedValue>
        </StatGroup>
      )}
    </dl>
  );
}

/**
 * One strategy as a card, the same on Explore, on My subscriptions and on My strategies. The title link is
 * stretched over the whole card, so the card opens the strategy; the switch, the open positions and each figure's
 * icon are lifted above it and keep their own action. The keyboard meets one stop, the title.
 */
export function StrategyCard(props: StrategyCardProps) {
  const { prefix } = props;
  const { t, i18n } = useTranslation();
  const dates = dateRange(props.since, i18n.language);

  return (
    <li
      data-testid={props.rowTestId}
      className="relative flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3 hover:bg-panel-2"
    >
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
          <p
            data-testid={`${prefix}-market`}
            className="flex flex-wrap items-center gap-x-1.5 font-mono text-[11px] text-ink-3"
          >
            <span className="uppercase tracking-[0.14em]">{props.market}</span>
            {dates !== null && (
              <>
                <span aria-hidden="true">·</span>
                <NamedValue
                  icon={Calendar}
                  label={t(props.sinceKind === "age" ? "strategies.card.age" : "strategies.card.subscribed")}
                  testId={`${prefix}-age`}
                >
                  {dates}
                </NamedValue>
              </>
            )}
          </p>
        </div>
      </div>
      {/* The card's one control is level with the figures, at the card's right end (owner, 2026-11-17): beside their
          grid, not in it, so however narrow the card no figure runs under it. */}
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <FigureGroups
            prefix={prefix}
            figures={props.figures}
            figuresError={props.figuresError}
            pnl={props.pnl}
            setup={props.setup}
          />
        </div>
        {props.action !== undefined && <div className="relative z-10 shrink-0">{props.action}</div>}
      </div>
      {props.marks !== undefined && <div className="relative z-10">{props.marks}</div>}
      {props.notice}
    </li>
  );
}
