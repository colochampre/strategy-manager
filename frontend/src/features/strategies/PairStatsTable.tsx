import { ArrowLeftRight, Coins, ListChecks, Target, TrendingUp } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/shared/lib/amount-text";
import { rateText } from "@/shared/lib/figure-text";
import type { PairStat } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { ColumnHead } from "@/shared/ui/ColumnHead";
import { ReportSection } from "@/shared/ui/ReportSection";

const DASH = "—";

/** A row of a record has no `pnl`: only a report in a currency carries money. */
type PairRow = Omit<PairStat, "pnl" | "return"> & { pnl?: string; return: string | null };

interface PairStatsTableProps {
  /** The report's `by_pair`, in the order the server gave it. No allowed-pairs list reaches this table: a pair removed from it keeps its history. */
  pairs: readonly PairRow[];
  /**
   * The strategy's pool currency; every PnL is in it (rule 7). Left out, the table is a public record: it has
   * no PnL column at all and invents no currency.
   */
  currency?: string;
}

interface ReadRow {
  pair: string;
  trades: number;
  /** The served rate, already written (cut at one decimal), never computed here. */
  winRate: string;
  /** Null in a record, which has no money. */
  pnl: number | null;
  /** Null is a pair with no return (no capital at open), which is not a zero. */
  ret: number | null;
}

const RATIO_TEXT = /^(\d+)(?:\.(\d+))?$/;

/**
 * Whether the served `rate` is `wins` over `trades`, in integers and without dividing anything. The ends
 * are exact (0 only with no wins, 1 only with every trade won, nothing above 1); between them the rate,
 * read as a whole number `r` over 10^scale, must sit within one unit of its last place of the true
 * fraction: `|r * trades - wins * 10^scale| <= trades`. That holds whichever way the server rounded it.
 */
function rateAgrees(wins: number, trades: number, rate: string): boolean {
  const match = RATIO_TEXT.exec(rate);
  if (match === null || !Number.isInteger(wins) || !Number.isInteger(trades)) return false;
  const fraction = match[2] ?? "";
  const scaled = BigInt(`${match[1] ?? ""}${fraction}`);
  const scale = 10n ** BigInt(fraction.length);
  if (scaled > scale) return false;
  if ((scaled === 0n) !== (wins === 0)) return false;
  if ((scaled === scale) !== (wins === trades)) return false;
  const gap = scaled * BigInt(trades) - BigInt(wins) * scale;
  return (gap < 0n ? -gap : gap) <= BigInt(trades);
}

/** Every row parsed, or `null` when any figure cannot be read: a table with one wrong figure is worse than none. */
function readRows(pairs: readonly PairRow[], locale: string, withMoney: boolean): ReadRow[] | null {
  const rows: ReadRow[] = [];
  for (const entry of pairs) {
    const pnl = withMoney && entry.pnl !== undefined ? parseDecimal(entry.pnl) : null;
    const ret = entry.return === null ? null : parseDecimal(entry.return);
    const winRate = rateAgrees(entry.wins, entry.trades, entry.win_rate) ? rateText(entry.win_rate, locale) : null;
    if ((withMoney && pnl === null) || (entry.return !== null && ret === null) || winRate === null) return null;
    rows.push({ pair: entry.pair, trades: entry.trades, winRate, pnl, ret });
  }
  return rows;
}

/**
 * "By pair": each pair's closed-trade count, realized PnL and return, in the
 * pool's own currency. The pair is the venue's spelling (`SOLUSDT`), as served.
 * It draws only when more than one pair has a closed trade; with one or none it is absent.
 * Figures are parsed only to be formatted; nothing is computed here.
 */
export function PairStatsTable({ pairs, currency }: PairStatsTableProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const locale = i18n.resolvedLanguage ?? "en";
  const rows = readRows(pairs, locale, currency !== undefined);

  // One pair, or none, only says again what the view's header says: the section is for comparing pairs.
  if (pairs.filter((entry) => entry.trades > 0).length < 2) return null;

  let body;
  if (rows === null) {
    body = (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.performance.byPair.unreadable")}
      </p>
    );
  } else {
    body = (
      <div className="overflow-x-auto">
        <table aria-labelledby={headingId} className="w-full border-collapse font-mono text-[13px] tabular-nums">
          <thead>
            <tr className="text-right text-[10px] uppercase tracking-[0.09em] text-ink-3">
              <th scope="col" className="border-b border-rule py-2 pr-3 text-left font-medium">
                <ColumnHead icon={ArrowLeftRight} label={t("strategies.performance.byPair.pair")} align="start" />
              </th>
              <th scope="col" className="border-b border-rule py-2 pr-3 font-medium">
                <ColumnHead icon={ListChecks} label={t("strategies.performance.byPair.trades")} />
              </th>
              <th scope="col" className="border-b border-rule py-2 pr-3 font-medium">
                <ColumnHead icon={Target} label={t("strategies.performance.byPair.winRate")} />
              </th>
              {currency !== undefined && (
                <th scope="col" className="border-b border-rule py-2 pr-3 font-medium">
                  <ColumnHead icon={Coins} label={t("strategies.performance.byPair.pnl", { currency })} />
                </th>
              )}
              <th scope="col" className="border-b border-rule py-2 font-medium">
                <ColumnHead icon={TrendingUp} label={t("strategies.performance.byPair.return")} />
              </th>
            </tr>
          </thead>
          <tbody className="text-right text-ink-2">
            {rows.map((row) => (
              <tr key={row.pair}>
                <td className="border-b border-rule-soft py-2.5 pr-3 text-left text-ink">{row.pair}</td>
                <td className="border-b border-rule-soft py-2.5 pr-3">{row.trades}</td>
                <td className="border-b border-rule-soft py-2.5 pr-3">{row.winRate}</td>
                {currency !== undefined && row.pnl !== null && (
                  <td className={cn("border-b border-rule-soft py-2.5 pr-3", toneClass(row.pnl))}>
                    {amountText(row.pnl, currency, locale, true)}
                  </td>
                )}
                <td className={cn("border-b border-rule-soft py-2.5", row.ret !== null && toneClass(row.ret))}>
                  {row.ret === null ? (
                    <>
                      <span aria-hidden="true">{DASH}</span>
                      <span className="sr-only">{t("strategies.performance.byPair.noReturn")}</span>
                    </>
                  ) : (
                    percentText(row.ret, locale)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <ReportSection>
      <section aria-labelledby={headingId} className="flex flex-col gap-2">
        <h2 id={headingId} className="font-display text-base font-semibold text-ink">
          {t("strategies.performance.byPair.title")}
        </h2>
        {body}
      </section>
    </ReportSection>
  );
}
