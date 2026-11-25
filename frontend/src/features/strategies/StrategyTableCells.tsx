import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ORIGIN_STYLE } from "@/features/positions/origin";
import { useEnableQuestion } from "@/features/strategies/EnableDialog";
import { dateRange, money } from "@/features/strategies/StrategyCard";
import type { CardFigures, CardPnl } from "@/features/strategies/StrategyCard";
import type { StrategyTableCell } from "@/features/strategies/StrategyTable";
import type { Strategy } from "@/shared/api/types";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { Masked } from "@/shared/hidden/Masked";
import { amountText, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { Tooltip } from "@/shared/ui/Tooltip";

/** What a figure shows where there is nothing true to say yet. */
const NO_FIGURE = "—";
/** What a figure shows while its report is on its way. */
const LOADING = "…";

/** The tone of a row's state dot: running, paused or leaving by someone else's doing, or off. */
export type DotTone = "gain" | "paused" | "off";

/**
 * The fill of each tone. Amber is written in one file of the positions unit (`panel-tokens.test.ts`): the paused dot
 * takes the amber of the mode badge from there, as the dry-run origin dot does.
 */
const DOT_FILL: Readonly<Record<DotTone, string>> = {
  gain: "bg-gain",
  paused: ORIGIN_STYLE.rehearsal.dot,
  off: "bg-ink-3",
};

/** Where a tip opens. The first row of a longer table opens its tips under the cell: above it, the box would cut them. */
export type TipPlacement = "above" | "below-start";

export function placementOf(index: number, count: number): TipPlacement {
  return index === 0 && count > 1 ? "below-start" : "above";
}

interface StateDotProps {
  tone: DotTone;
  /** What the dot means, in words: its accessible name and its tooltip. */
  label: string;
  testId: string;
  placement: TipPlacement;
}

/**
 * A strategy's state as a small coloured dot beside its name (L17's dot, as the Overview draws a position's origin):
 * gain when it runs, amber when it is paused, grey when it is off or leaving. The tip repeats the name, so it does not
 * also describe the trigger.
 */
export function StateDot({ tone, label, testId, placement }: StateDotProps) {
  return (
    <Tooltip text={label} describes={false} placement={placement}>
      <span
        role="img"
        aria-label={label}
        data-testid={testId}
        className={cn("block size-2 shrink-0 rounded-full", DOT_FILL[tone])}
      />
    </Tooltip>
  );
}

interface NameCellProps {
  to: string;
  name: string;
  dot: ReactNode;
  archived?: boolean;
}

/** The dot and the strategy's name, the name a link to its page (S15). */
export function NameCell({ to, name, dot, archived = false }: NameCellProps) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-2">
      {dot}
      <Link to={to} className="text-gain hover:text-gain-bright">
        {name}
      </Link>
      {archived && <span className="text-[11px] uppercase tracking-wide text-ink-3">{t("strategies.row.archived")}</span>}
    </span>
  );
}

/** One pair is its symbol; several are their count, dotted, and the list is in the tooltip (L22). */
export function PairsCell({ pairs, testId, placement }: { pairs: readonly string[]; testId: string; placement: TipPlacement }) {
  const { t } = useTranslation();
  if (pairs.length === 0) return <span data-testid={testId}>{NO_FIGURE}</span>;
  if (pairs.length === 1) {
    return (
      <span data-testid={testId} className="font-mono text-ink">
        {pairs[0]}
      </span>
    );
  }
  return (
    <Tooltip text={pairs.join(", ")} placement={placement} className="cursor-help">
      <span data-testid={testId} className="underline decoration-dotted decoration-ink-3 underline-offset-4">
        {t("strategies.table.pairsCount", { count: pairs.length })}
      </span>
    </Tooltip>
  );
}

/** The day a strategy started, as the prototype's "21 oct 2026". */
function startText(since: string, locale: string): string | null {
  const from = Date.parse(since);
  if (Number.isNaN(from)) return null;
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(from));
}

/** The start date, with the whole period (from it to today) in the tooltip. A date that cannot be read is a dash. */
export function SinceCell({ since, testId, placement }: { since: string | null; testId: string; placement: TipPlacement }) {
  const { i18n } = useTranslation();
  const start = since === null ? null : startText(since, i18n.language);
  const range = dateRange(since, i18n.language);
  if (start === null || range === null) return <span data-testid={testId}>{NO_FIGURE}</span>;
  return (
    <Tooltip text={range} describes={false} placement={placement}>
      <span data-testid={testId}>{start}</span>
    </Tooltip>
  );
}

/** The exchange's name, with its market and settlement currency in the tooltip ("Bybit · USDT-M · USDT"). */
export function ExchangeCell({
  exchange,
  venue,
  currency,
  testId,
  placement,
}: {
  exchange: string;
  venue: string;
  currency: string;
  testId: string;
  placement: TipPlacement;
}) {
  const { t, i18n } = useTranslation();
  const name = exchangeName(t, i18n, exchange);
  return (
    <Tooltip text={`${name} · ${venue.toUpperCase()} · ${currency}`} describes={false} placement={placement}>
      <span data-testid={testId}>{name}</span>
    </Tooltip>
  );
}

/** The one currency of a list's rows, or null where they differ: a header names it only when it is true of every row (rule 7). */
export function commonOf(values: readonly string[]): string | null {
  const first = values[0];
  return first !== undefined && values.every((value) => value === first) ? first : null;
}

function moneyNode(amount: number | null | undefined, currency: string, locale: string, signed: boolean, unit: boolean): ReactNode {
  if (unit) return money(amount, currency, locale, signed);
  if (amount === undefined) return LOADING;
  if (amount === null) return NO_FIGURE;
  return <Masked>{amountText(amount, currency, locale, signed)}</Masked>;
}

/** A signed ratio as the prototype writes it, "+5,2%": the sign of the number and the percent sign right after it. */
function percentNode(ratio: number | null | undefined, locale: string): { value: ReactNode; tone: string | undefined } {
  if (ratio === undefined) return { value: LOADING, tone: undefined };
  if (ratio === null) return { value: NO_FIGURE, tone: undefined };
  return { value: `${percentText(ratio, locale, false)}%`, tone: toneClass(ratio) };
}

function rateText(value: number | null | undefined, locale: string): string {
  if (value === undefined) return LOADING;
  if (value === null) return NO_FIGURE;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

function countText(value: number | null | undefined): string {
  return value === undefined ? LOADING : value === null ? NO_FIGURE : String(value);
}

interface RecordCellsInput {
  prefix: string;
  figures: CardFigures;
  locale: string;
  /** The PnL in money, in its pool's currency: absent where the list draws none (Explore shows another author's return only). */
  pnl?: CardPnl;
  /** The header does not name one currency, so each amount carries its own. */
  unit: boolean;
  /** Said once across the record's columns, in place of the figures, when the report failed. */
  error?: string | null;
}

/**
 * The record's columns, in the order of the prototype: the PnL in money where there is one, the PnL in percent, the
 * deepest fall and the win rate with its count. A failed report is one cell across all of them.
 */
export function recordCells({ prefix, figures, locale, pnl, unit, error = null }: RecordCellsInput): StrategyTableCell[] {
  if (error !== null) {
    return [
      {
        span: pnl === undefined ? 3 : 4,
        content: (
          <p role="alert" className="text-xs text-loss">
            {error}
          </p>
        ),
      },
    ];
  }
  const ret = percentNode(figures.ret, locale);
  const deepest = percentNode(figures.deepest, locale);
  const wins = figures.profitable;
  const cells: StrategyTableCell[] = [];
  if (pnl !== undefined) {
    const value = pnl.value;
    cells.push({
      content: (
        <span data-testid={`${prefix}-pnl`} className={value === undefined || value === null ? undefined : toneClass(value)}>
          {moneyNode(pnl.value, pnl.currency, locale, true, unit)}
        </span>
      ),
    });
  }
  cells.push(
    {
      content: (
        <span data-testid={`${prefix}-return`} className={ret.tone}>
          {ret.value}
        </span>
      ),
    },
    {
      content: (
        <span data-testid={`${prefix}-deepest`} className={deepest.tone}>
          {deepest.value}
        </span>
      ),
    },
    {
      content: (
        <>
          <span data-testid={`${prefix}-winrate`}>{rateText(figures.winRate, locale)}</span>
          {wins !== undefined && wins !== null && (
            <>
              {" · "}
              <span data-testid={`${prefix}-wins`} className="text-ink-2">
                {`${wins.wins}/${wins.closed}`}
              </span>
            </>
          )}
        </>
      ),
    },
  );
  return cells;
}

/** The AuM columns: who trades the strategy live, and with how much (the capital carries no unit where the header names it). */
export function aumCells({ prefix, figures, locale, unit }: { prefix: string; figures: CardFigures; locale: string; unit: boolean }): StrategyTableCell[] {
  const capital = figures.capital;
  return [
    { content: <span data-testid={`${prefix}-subscribers`}>{countText(figures.subscribers)}</span> },
    {
      content: (
        <span data-testid={`${prefix}-capital`}>
          {capital === null || capital === undefined
            ? moneyNode(capital, "", locale, false, false)
            : moneyNode(capital.amount, capital.currency, locale, false, unit)}
        </span>
      ),
    },
  ];
}

/**
 * Enables or disables a strategy after asking (`useEnableQuestion`): a text button of its own width at the end of the
 * row, Disable in the loss tone and Enable in the gain tone (L21). An archived strategy never changes again, so its
 * button is unavailable. A refused or failed change says so inside the question.
 */
export function EnableButton({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation();
  const question = useEnableQuestion(strategy);
  const running = strategy.enabled;
  return (
    <>
      <button
        type="button"
        aria-label={t(running ? "strategies.table.disableLabel" : "strategies.table.enableLabel", { name: strategy.name })}
        disabled={strategy.archived_at !== null || question.busy}
        onClick={question.ask}
        className={cn(
          "inline-flex h-[30px] w-24 items-center justify-center rounded-lg border px-[11px] text-[13px] font-medium disabled:opacity-50",
          running ? "border-loss/55 text-loss hover:bg-loss/10" : "border-gain/45 text-gain-bright hover:bg-gain/10",
        )}
      >
        {t(running ? "strategies.table.disable" : "strategies.table.enable")}
      </button>
      {question.dialog}
    </>
  );
}
