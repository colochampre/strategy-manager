import { Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { amountText, percentText, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { Masked } from "@/shared/hidden/Masked";
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
      <Masked>{amountText(amount, currency, locale, signedAmount)}</Masked>
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
